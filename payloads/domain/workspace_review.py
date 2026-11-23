"""Source-bound counsel reading view; no new inference, approvals or source acquisition."""
import hashlib
from types import SimpleNamespace

from .case_brief import build as build_case_brief
from .financial_review import build as reconcile
from .workspace_case_map import case_map
from .workspace_projection import CASE_QUESTION_GUIDANCE


def verify(workspace):
    sources = {s['source_id']: s for s in workspace['sources']}
    evidence = {p['evidence_id']: p for p in workspace['evidence']}
    for source in sources.values():
        if source['text'] is not None and hashlib.sha256(source['text'].encode()).hexdigest() != source['content_sha256']:
            raise ValueError('Reading view source hash mismatch')
    for passage in evidence.values():
        source = sources.get(passage['source_id'])
        a, b = passage['start_offset'], passage['end_offset']
        if (source is None or source['text'] is None or passage['content_sha256'] != source['content_sha256']
                or not 0 <= a < b <= len(source['text']) or source['text'][a:b] != passage['text']):
            raise ValueError('Reading view citation mismatch')
    for event in workspace.get('financial_review', {}).get('events', []):
        if not event['evidence_ids'] or any(i not in evidence or evidence[i]['source_id'] != event['source_id']
                or evidence[i]['text'] != event['quote'] for i in event['evidence_ids']):
            raise ValueError('Reading view financial basis mismatch')
    fields = ('source_id', 'quote', 'event_type', 'amount', 'currency', 'transaction_ref', 'ledger_id', 'record_id', 'event_date')
    financial = reconcile({'financial_events': [{k: r[k] for k in fields if k in r}
        for r in workspace.get('financial_review', {}).get('events', [])]},
        [SimpleNamespace(**s) for s in sources.values()], {})
    return financial


def attach(workspace):
    from .review_packets import consistency_checks

    # Recompute totals from verified annotated quotations rather than cached totals.
    workspace['financial_review'] = verify(workspace)
    workspace.setdefault('capabilities', {})['case_qa'] = CASE_QUESTION_GUIDANCE
    checks = consistency_checks({'findings': workspace['findings']}, workspace['financial_review'])
    evidence_ids = {p['evidence_id'] for p in workspace['evidence']}
    checks += [c for c in workspace.get('consistency', {}).get('checks', [])
        if set(c.get('evidence_ids', [])) <= evidence_ids and c not in checks]
    blocked = {c['finding_id'] for c in checks}
    workspace['reading_review'] = {'checks': checks, 'withheld_finding_ids': sorted(blocked),
        'definition': 'Limited checks for explicit absence claims and annotated ledger conflicts. Passing is not a substantive accuracy determination.'}
    workspace['reading_tasks'] = review_tasks(workspace)
    from .supervision import build as build_handoff
    workspace['supervision'] = build_handoff(workspace)
    workspace['case_brief'] = build_case_brief(workspace)
    workspace['case_map'] = case_map(workspace)
    workspace['reading_reports'] = reports(workspace)
    return workspace


def md(value):
    return str(value or '').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')


def review_tasks(workspace):
    tasks = []
    financial = workspace['financial_review']
    for t in financial['transactions']:
        records = [r for r in financial['events'] if all(r[k] == t[k] for k in ('transaction_ref', 'currency', 'ledger_id'))]
        approved = [r for r in records if r['event_type'] == 'approved']
        postings = [r for r in records if r['event_type'] in {'posting', 'reversal', 'net_balance'}]
        if approved:
            tasks.append({'title': 'Confirm the scope of written approval', 'status': 'Internal reread',
                'record': 'The request and stated approval for ' + t['transaction_ref'],
                'purpose': 'Distinguish the amount requested from the amount approved. Read conditions and any exception requirements in context.',
                'closure': 'Record the authorized amount, any conditions and the source basis for any larger approval.',
                'evidence_ids': [i for r in records if r['event_type'] in {'requested', 'approved'} for i in r['evidence_ids']]})
        if postings:
            tasks.append({'title': 'Reconcile the posting and reversal', 'status': 'Internal reread',
                'record': 'Ledger records for ' + t['transaction_ref'],
                'purpose': 'Test any loss statement against the supplied posting, reversal and recorded net. Keep accounting and external settlement separate.',
                'closure': 'Tie the selected ledger entries and net to their original records and explain any discrepancy.',
                'evidence_ids': [i for r in postings for i in r['evidence_ids']]})
        if not any(r['event_type'] == 'settlement' for r in records):
            tasks.append({'title': 'Resolve external bank settlement', 'status': 'Evidence check',
                'record': 'Bank statements, confirmation or settlement records for ' + t['transaction_ref'],
                'purpose': 'No source-bound settlement annotation was supplied. Inspect the full materials before deciding which bank-side records counsel should request.',
                'closure': 'Source-backed reconciliation of external settlement with the ledger, or a documented remaining limitation.',
                'evidence_ids': t['evidence_ids']})
    for i, task in enumerate(tasks):
        task.update(id='reading-task-' + str(i), owner='Unassigned', origin='Proposed internal review; no collection or contact performed')
    return tasks


def reports(workspace):
    from .supervision import markdown as review_question
    from .review_products import finding_wording
    blocked = set(workspace['reading_review']['withheld_finding_ids'])
    retained = set(workspace['supervision']['retained_finding_ids'])
    financial = workspace['financial_review']
    brief = workspace['case_brief']
    passages = {p['evidence_id']: p for p in workspace['evidence']}
    numbers = {ident: n for n, ident in enumerate(dict.fromkeys([*brief['cited_ids'], *passages]), 1)}

    def citations(ids):
        return ' '.join(f'[Passage {numbers[i]}](exact-source-passages.md#{i})' for i in dict.fromkeys(ids))

    lines = ['# Counsel review brief', '', '**Draft for attorney review.**', '', '## Review objective', '',
             md(workspace.get('matter_scope', {}).get('intended_decision') or workspace['goal']), '']
    if workspace.get('sample'):
        lines += ['Synthetic test matter.', '']
    if retained:
        lines += ['## Retained draft findings', '']
    for f in workspace['findings']:
        if f['id'] in retained:
            lines += ['### ' + md(f['title']), '', md(finding_wording(f)), '', citations(f['supporting_evidence']), '']
            if f.get('counter_evidence'):
                lines += ['**Contrary records** ' + citations(f['counter_evidence']), '']
            lines += ['**Limitations** ' + md(f['limitations']), '']
    if not retained:
        lines += ['No finding cleared review for inclusion in this brief.', '']
    if brief['highlights']:
        lines += ['## What the records say', '', 'Selected excerpts from documents cited in this review.', '']
    for highlight in brief['highlights']:
        ident = highlight['evidence_id']
        title = brief['titles'][passages[ident]['source_id']]
        lines += [md(title), '', *['> ' + line for line in highlight['excerpt'].splitlines()],
                  '', citations([ident]), '']
    lines += [review_question(workspace, appendix='exact-source-passages.md#'), '']
    if financial['events']:
        lines += ['## What the transaction records show', '',
                  '| Reference | Recorded event | Amount | Basis |', '| --- | --- | ---: | --- |']
    for record in financial['events']:
        lines.append('| ' + ' | '.join([md(record['transaction_ref']), md(record['event_type'].replace('_', ' ')),
            md(record['currency'] + ' ' + record['amount']), citations(record['evidence_ids'])]) + ' |')
    for t in financial['transactions']:
        lines += ['', '### ' + md(t['transaction_ref']), '',
            '- Request less stated approval: ' + md(t['currency']) + ' ' + md(t['request_minus_approval'] or 'Not established') + '.',
            '- Posting / reversal net: ' + md(t['currency']) + ' ' + md(t['posting_reversal_net'] or 'Not established') + '.',
            '- Recorded net values: ' + md(', '.join(t['recorded_net_values']) or 'Not supplied') + '.', '',
            citations(t['evidence_ids']), '', md(t['qualification'])]
    if workspace.get('counsel_issues'):
        lines += ['', '## Counsel questions', '', 'Counsel-supplied review direction; applicable law is not verified.', '']
        for issue in workspace['counsel_issues']:
            linked = [f for f in workspace['findings'] if f['id'] in retained and issue['id'] in f.get('counsel_issue_ids', [])]
            lines += ['### ' + md(issue['question']), '',
                md(' '.join(finding_wording(f) for f in linked) or issue['status']), '',
                citations([i for f in linked for i in f['supporting_evidence']]), '']
    if workspace.get('issues'):
        lines += ['## Questions examined', '']
    for issue in workspace.get('issues', []):
        lines += ['### ' + md(issue['question']), '', 'Investigator assessment · ' + md(issue['status']), '']
        for label, key in [('Records considered', 'supporting_evidence'), ('Contrary passages', 'contradictory_evidence')]:
            if issue[key]:
                lines += [label + ' · ' + citations(issue[key]), '']
    if blocked:
        lines += ['## Draft claims requiring correction', '']
    for f in workspace['findings']:
        if f['id'] in blocked:
            ids = [i for c in workspace['reading_review']['checks'] if c['finding_id'] == f['id'] for i in c['evidence_ids']]
            lines += ['### ' + md(f['title']), '', 'Withheld from the reading brief and reviewed briefing. An available transaction record conflicts with an absence claim. Reconcile the complete source before relying on this wording.', '', citations(ids), '']
    if workspace['reading_tasks'] or workspace['gaps']:
        lines += ['## Next review work', '']
    for task in workspace['reading_tasks']:
        lines += ['### ' + md(task['title']), '', '- Route: ' + md(task['status']),
            '- Record: ' + md(task['record']), '- Decision it informs: ' + md(task['purpose']),
            '- Closure test: ' + md(task['closure']), '- Owner: Unassigned', '', citations(task['evidence_ids']), '']
    for gap in workspace['gaps']:
        lines += ['### ' + md(gap['question']), '',
            '- **Record to check** ' + md(gap.get('requested_record') or gap['question']),
            '- **What would resolve it** ' + md(gap['closure_condition'])]
        if gap.get('owner') and gap['owner'] != 'Unassigned':
            lines.append('- **Assigned to** ' + md(gap['owner']))
        if gap.get('internal_target'):
            lines.append('- **Internal target** ' + md(gap['internal_target']))
        lines += ['', citations(gap['source_evidence_ids']), '']
    lines += ['## Scope and limits', '', md(workspace['analysis']['scope']), '']
    source_ids = set(brief['titles'])
    coverage = workspace.get('coverage', {})
    for key, label in [('readable_ids', 'Readable documents'), ('assessor_source_ids', 'Sent for assessment'),
                       ('reviewer_source_ids', 'Sent for independent review')]:
        if key in coverage:
            lines.append(f'- {label} · {len(source_ids.intersection(coverage[key]))} of {len(source_ids)}')
    lines += ['', 'The counts describe document access and model review. Counsel must verify the evidence and decide how to use it.']
    appendix = ['# Exact source passages', '', 'Generated normalized character locators. Verify originals and surrounding context.', '']
    for ident, number in numbers.items():
        p = passages[ident]
        appendix += ['## ' + ident, '', f"Passage {number} · " + md(brief['titles'][p['source_id']]), '',
            md(p['source_id']) + f" · characters {p['start_offset']}:{p['end_offset']}", '',
            *['> ' + line for line in p['text'].splitlines()], '']
    return [{'id': 'counsel-brief', 'title': 'Counsel review brief', 'filename': 'counsel-review-brief.md', 'markdown': '\n'.join(lines)},
        {'id': 'source-passages', 'title': 'Exact source passages', 'filename': 'exact-source-passages.md', 'markdown': '\n'.join(appendix)}]
