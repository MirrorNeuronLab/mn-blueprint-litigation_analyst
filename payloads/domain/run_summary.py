"""Compact authoritative handoff, independent of optional webpage rendering."""

from urllib.parse import quote

from .review_products import escaped, finding_wording, passage_links
from .supervision import build, chat_summary


def render(workspace, *, appendix_ids=()):
    summary = chat_summary(workspace)
    handoff = build(workspace)
    retained = set(handoff['retained_finding_ids'])
    lines = ['# Litigation review summary', '', escaped(summary['overview']), '']
    visible = [f for f in workspace['findings'] if f['id'] in retained]
    for highlight, finding in zip(summary['highlights'], visible):
        wording, limitations = finding_wording(finding), finding['limitations']
        lines += ['## ' + escaped(highlight['title']), '']
        if len((wording + limitations).encode()) <= 1600:
            label = 'Reviewed wording excerpt: ' if wording != finding['assessment'] else 'Draft excerpt: '
            lines += [label + escaped(wording), '', escaped(limitations), '']
        else:
            lines += ['Read the complete finding and its qualifications in the [review draft](final_report.md).', '']
        ids = [eid for eid in finding.get('evidence_ids', finding['supporting_evidence']) if eid in appendix_ids]
        if ids:
            lines += [passage_links(ids[:4], finding.get('citation_keys')), '']
    coverage = workspace.get('coverage', {})
    if not retained and any(p['stage'] == 'assessment' for p in coverage.get('model_packets', [])):
        outcome = ('The assessment received no source passages.' if not coverage.get('assessor_source_ids')
                   else 'No finding cleared review for this draft.')
        lines += [outcome + ' See the questions examined in the [review draft](final_report.md).', '']
    lines += ['## Analysis and limits', '', escaped(summary['status']) + '.', '',
        f"{len(coverage.get('assessor_source_ids', []))} source records sent for assessment; "
        f"{len(coverage.get('reviewer_source_ids', []))} sent for independent review. "
        'These counts do not establish complete review or attorney approval.', '',
        escaped(summary['limitation']), '',
        '## Your next review', '', escaped(summary['review']['question']), '',
        escaped(summary['review']['reason']), '', escaped(summary['review']['timing']), '']
    passages = [eid for eid in handoff['next_review']['evidence_ids'] if eid in appendix_ids]
    if passages:
        links = [f"[Passage {i}](evidence_appendix.md#evidence-{quote(eid, safe='')})"
                 for i, eid in enumerate(passages[:4], 1)]
        lines += ['Passages for this review: ' + ' · '.join(links), '']
    lines += ['## Output files', '',
        '- [Review draft](final_report.md): findings, contrary evidence and review coverage.',
        '- [Evidence appendix](evidence_appendix.md): exact source passages.',
        '- [Graph appendix](graph_appendix.md): observed relationships and their limits.',
        '- [Transaction appendix](transaction_appendix.md): source-bound financial records.',
        '- [Review index](review_index.json): saved reports and audit locations.', '']
    return '\n'.join(lines)
