"""Attorney-facing issue coverage and independently cited arithmetic exhibits."""
import html

from mn_temporal_graph_skill import fingerprint

from .financial_review import build as reconcile


def attach(workspace, context, matter, documents, spans, plan):
    visible = {d.source_id for d in documents}
    financial = reconcile({**matter, "financial_events": [r for r in matter["financial_events"] if r["source_id"] in visible]}, documents, {})
    for row in financial["evidence"]:
        spans.setdefault(row["evidence_id"], row)
    workspace["evidence"] = list(spans.values())
    workspace["financial_review"] = financial
    workspace["matter_scope"] = {k: matter[k] for k in ("intended_decision", "parties", "transaction_refs")}
    rows = []
    for issue in matter["issues"]:
        linked = [h for h in workspace["issues"] if issue["id"] in h.get("counsel_issue_ids", [])]
        rows.append({**issue, "status": "Examined through AI hypotheses; requires attorney review" if linked else "Unexamined in this review",
            "framework_basis": "Counsel-supplied review direction, not verified applicable law or case evidence",
            "hypothesis_ids": [h["id"] for h in linked],
            "supporting_evidence": list(dict.fromkeys(i for h in linked for i in h["supporting_evidence"])),
            "counter_evidence": list(dict.fromkeys(i for h in linked for i in h["contradictory_evidence"])),
            "unknowns": list(dict.fromkeys(q for h in linked for q in h["outstanding_enquiries"])),
            "gap_ids": list(dict.fromkeys(i for h in linked for i in h["gap_ids"]))})
    workspace["counsel_issues"] = rows
    for finding in workspace["findings"]:
        related = [row for row in rows if set(row["hypothesis_ids"]) & set(finding["issue_ids"])]
        finding["counsel_issue_ids"] = [row["id"] for row in related]
        finding["material_digest"] = fingerprint([finding["material_digest"], workspace["matter_scope"],
            [{k: row.get(k) for k in ("id", "question", "legal_framework")} for row in related]])
    workspace["analysis"]["review_plan"] = plan
    workspace["analysis"]["unexamined_issue_ids"] = [r["id"] for r in rows if not r["hypothesis_ids"]]
    workspace["analysis"]["partial_review"] = plan["profile"] == "first_pass" or bool(workspace["analysis"]["unexamined_issue_ids"]) or workspace["analysis"]["status"] == "Incomplete analysis"
    if plan["profile"] == "first_pass" and workspace["analysis"].get("stop_reason") == "maximum_rounds_reached" and workspace["issues"]:
        workspace["analysis"]["status"] = "First pass complete — draft for attorney review"
    elif workspace["analysis"]["partial_review"] and workspace["analysis"]["status"] != "Incomplete analysis":
        workspace["analysis"]["status"] = "Partial review — draft for attorney review"
    workspace["capabilities"]["financial_scenarios"] = financial["status"] + "; arithmetic only, no damages or settlement determination"
    workspace["capabilities"]["legal_elements"] = "Counsel-provided issues/framework; legal applicability remains unverified" if rows else "Unavailable: counsel-defined framework not supplied"
    workspace["snapshot_id"] = fingerprint([workspace["snapshot_id"], workspace["matter_scope"], rows, financial, plan])
    return workspace


def escaped(value):
    if value is None:
        return 'Unresolved'
    value = html.escape(str(value))
    for char in "[]()*_`":
        value = value.replace(char, "\\" + char)
    return value


def transaction_appendix(financial):
    lines = ["# Transaction reconciliation", "", financial["status"], "",
        "Event classifications, ledger grouping and any supplied dates are counsel annotations. Exact quotations and recorded numbers are verified; legal effect and external settlement are not.", ""]
    for transaction in financial["transactions"]:
        lines += ["## " + escaped(transaction["transaction_ref"]) + " · " + escaped(transaction["currency"]), "",
            "Ledger group (counsel annotation): " + escaped(transaction["ledger_id"]), "",
            "Posting / reversal net: " + escaped(transaction["posting_reversal_net"]),
            "Recorded net values: " + escaped(", ".join(transaction["recorded_net_values"])),
            "Request minus stated approval: " + escaped(transaction["request_minus_approval"]), "",
            transaction["qualification"], ""]
    for evidence in financial["evidence"]:
        lines += [f'<a id="evidence-{evidence["evidence_id"]}"></a>',
            "### Exact transaction passage " + evidence["evidence_id"], "",
            escaped(evidence["source_id"]) + " · normalized SHA-256 " + evidence["content_sha256"] +
            f" · generated character span {evidence['start_offset']}:{evidence['end_offset']}", "",
            *["> " + html.escape(line) for line in evidence["text"].splitlines()], ""]
    return "\n".join(lines)


def passage_links(ids, keys=None):
    keys = keys or {}
    return ' · '.join(f'[Passage {keys.get(eid, n)}](evidence_appendix.md#evidence-{eid})'
                      for n, eid in enumerate(dict.fromkeys(ids), 1))


def finding_wording(finding):
    if finding.get('review_state') in {'Reviewed with qualification', 'Revised'} and finding.get('reviewed_text'):
        return finding['reviewed_text']
    return finding['assessment']


def report_sections(workspace, retained):
    lines = []
    if workspace["counsel_issues"]:
        lines += ["## Counsel issue coverage", ""]
    for issue in workspace["counsel_issues"]:
        findings = [f for f in retained if issue['id'] in f.get('counsel_issue_ids', [])]
        lines += ["### " + escaped(issue["id"]) + ": " + escaped(issue["question"]), "", escaped(issue["status"]), "",
            escaped(' '.join(finding_wording(f) for f in findings) or 'This question remains open.'), ""]
        for label, ids in [('Supporting records', issue['supporting_evidence']), ('Contrary records', issue['counter_evidence'])]:
            if ids:
                lines += [label + ' · ' + passage_links(ids), '']
        lines.extend(escaped(q) + '\n' for q in issue['unknowns'])
    plan = workspace["analysis"]["review_plan"]
    lines += ["## Review allowance and unexamined scope", "",
        f"Profile: {plan['profile']}. Up to {plan['max_rounds']} round(s), {plan['max_decisions']} investigation decisions, plus one separate readiness decision and {plan['relationship_call_ceiling']} separate relationship-extraction decisions.",
        f"Planning-boundary time allowance: {plan['seconds']} seconds; an in-flight request can extend elapsed time.",
        plan["definition"], ""]
    external = [g for g in workspace['gaps'] if g.get('work_type') not in {'internal_reread', 'handling_review'}]
    if plan.get("objective") == "discovery":
        lines += ["## Discovery preparation", ""]
        if not external:
            lines += ["This review identified no specific additional record to request. Counsel can check coverage against the request.", ""]
    elif external:
        lines += ["## Next evidence work", ""]
    for gap in external:
        lines += ["### " + escaped(gap["question"]), "",
            "Record or interview requested: " + escaped(gap["requested_record"]),
            "Decision it informs: " + escaped(gap["why_it_matters"]),
            "Closure test: " + escaped(gap["closure_condition"]),
            "Proposed priority: " + escaped(gap["priority"]) + " — " + escaped(gap["priority_basis"]), ""]
        if gap.get("owner") and gap['owner'] != 'Unassigned':
            lines += ["Owner · " + escaped(gap["owner"]), ""]
        if gap.get("internal_target"):
            lines += ["Internal target · " + escaped(gap["internal_target"]), ""]
        if gap['source_evidence_ids']:
            lines += [passage_links(gap['source_evidence_ids']), ""]
    if workspace['financial_review']['events']:
        lines += ["[Source-bound transaction reconciliation](transaction_appendix.md)", ""]
    return "\n".join(lines)


def issue_brief(workspace):
    from .supervision import build, markdown as review_question
    retained_ids = set(build(workspace)['retained_finding_ids'])
    retained = [f for f in workspace['findings'] if f['id'] in retained_ids]
    objective = workspace["analysis"]["review_plan"].get("objective", "investigation")
    finding_heading = "Record citations for counsel" if objective == "court_preparation" else "Reviewed findings"
    lines = ['# Litigation review draft', '', '**Draft for attorney review. Source authenticity and legal effect remain unverified.**', '',
        '## ' + finding_heading, '']
    for finding in retained:
        lines += ['### ' + escaped(finding['title']), '',
                  escaped(finding_wording(finding)), '',
                  escaped(finding['limitations']), '',
                  passage_links(finding.get('evidence_ids', finding['supporting_evidence']), finding.get('citation_keys')), '']
    if not retained:
        lines += ['No finding cleared review for this draft.', '']
    if workspace['issues']:
        heading = {"case_strategy": "Competing accounts", "witness_preparation": "Witness questions and exhibits"}.get(objective, "Questions examined")
        lines += ['## ' + heading, '']
    for issue in workspace['issues']:
        lines += ['### ' + escaped(issue['question']), '', 'Assessor outcome · ' + escaped(issue['status']), '']
        if objective in {"witness_preparation", "case_strategy"}:
            for label, ids in (("Supporting passages", issue["supporting_evidence"]),
                               ("Contrary passages", issue["contradictory_evidence"])):
                if ids:
                    lines += [label + " · " + passage_links(ids), ""]
            if objective == "case_strategy":
                lines.extend("Alternative account · " + escaped(a) + "\n" for a in issue["alternatives"])
        elif issue['supporting_evidence'] or issue['contradictory_evidence']:
            lines += ['Records considered · ' + passage_links(issue['supporting_evidence'] + issue['contradictory_evidence']), '']
        if issue['outstanding_enquiries']:
            label = "Proposed follow-up" if objective == "witness_preparation" else "Still open"
            lines += [label + ' · ' + escaped(issue['outstanding_enquiries'][0]), '']
    lines += [review_question(workspace), '']
    financial = workspace['financial_review']
    if financial['events']:
        lines += ['### Available transaction records', '',
            '| Reference | Recorded event (counsel classification) | Currency | Amount | Source |',
            '| --- | --- | --- | ---: | --- |']
    for e in financial['events']:
        eid = e['evidence_ids'][0]
        lines.append('| ' + ' | '.join([escaped(e['transaction_ref']), escaped(e['event_type']),
            escaped(e['currency']), escaped(e['amount']), f'[Exact passage](transaction_appendix.md#evidence-{eid})']) + ' |')
    for t in financial['transactions']:
        lines += ['', escaped(t['transaction_ref']) + ': request minus stated approval = ' + escaped(t['request_minus_approval']) +
            '; posting/reversal net = ' + escaped(t['posting_reversal_net']) + '; recorded net = ' + escaped(', '.join(t['recorded_net_values'])) + '.']
    if financial['transactions']:
        lines += ['', 'External settlement and loss require independent source records.', '']
    lines += [report_sections(workspace, retained)]
    contrary_issues = [i for i in workspace['issues'] if i['contradictory_evidence'] or
                       (i['alternatives'] and objective != "case_strategy")]
    if contrary_issues:
        lines += ['## Contrary evidence and qualifications', '']
    for issue in contrary_issues:
        lines += [escaped(issue['question']), '']
        if objective != "case_strategy":
            lines.extend('- ' + escaped(a) for a in issue['alternatives'])
        lines.append('')
        by_id = {e['evidence_id']:e for e in workspace['evidence']}
        for eid in issue['contradictory_evidence'][:3]:
            evidence = by_id[eid]
            lines += ['[Exact contrary passage](evidence_appendix.md#evidence-' + eid + ') · ' + escaped(evidence['source_id']), '']
            if len(evidence['text'].encode()) <= 2000:
                lines += ['> ' + html.escape(line) for line in evidence['text'].splitlines()]
                lines += ['']
    internal = [g for g in workspace['gaps'] if g.get('work_type') in {'internal_reread','handling_review'}]
    if internal:
        lines += ['## Internal review work', '']
        for gap in internal:
            lines += ['- ' + escaped(gap['status']) + ' · ' + escaped(gap['requested_record']) + '. ' + escaped(gap['routing_reason'])]
    coverage = workspace['coverage']
    lines += ['', '## Evidence review coverage', '',
        f"{len(coverage['readable_ids'])} of {len(coverage['source_ids'])} cleared source records contain readable text. {len(coverage.get('duplicate_source_groups', []))} duplicate groups are not independent corroboration.",
        f"{len(coverage.get('attachment_processing', []))} attachment processing notices; {len(coverage.get('archives_not_extracted', []))} archives remain unextracted. See case/source_inventory.json.",
        f"{len(coverage.get('assessor_source_ids', []))} source records admitted to assessor packets; {len(coverage.get('reviewer_source_ids', []))} to reviewer packets.",
        'Packet admission does not certify complete extraction, model comprehension or attorney review.',
        'Consistency status: ' + escaped(workspace.get('consistency', {}).get('status', 'unmeasured')), '']
    if workspace.get('consistency', {}).get('withheld_finding_ids'):
        lines += ['Some draft claims were withheld for consistency review. See case/consistency_review.json; their wording is not an accepted finding.', '']
    return '\n'.join(lines)
