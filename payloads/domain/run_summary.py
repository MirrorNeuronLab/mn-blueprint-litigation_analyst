"""Compact authoritative handoff, independent of optional webpage rendering."""

from .review_products import escaped
from .supervision import chat_summary


def render(workspace):
    summary = chat_summary(workspace)
    lines = ['# Litigation review summary', '', escaped(summary['overview']), '']
    for finding in summary['highlights']:
        lines += ['## ' + escaped(finding['title']), '', escaped(finding['detail']), '']
    coverage = workspace.get('coverage', {})
    lines += ['## Analysis and limits', '', escaped(summary['status']) + '.', '',
        f"{len(coverage.get('assessor_source_ids', []))} source records sent for assessment; "
        f"{len(coverage.get('reviewer_source_ids', []))} sent for independent review. "
        'These counts do not establish complete review or attorney approval.', '',
        escaped(summary['limitation']), '',
        '## Your next review', '', escaped(summary['review']['question']), '',
        escaped(summary['review']['reason']), '', escaped(summary['review']['timing']), '',
        '## Output files', '',
        '- [Review draft](final_report.md): findings, contrary evidence and review coverage.',
        '- [Evidence appendix](evidence_appendix.md): exact source passages.',
        '- [Graph appendix](graph_appendix.md): observed relationships and their limits.',
        '- [Transaction appendix](transaction_appendix.md): source-bound financial records.',
        '- [Review index](review_index.json): saved reports and audit locations.', '']
    return '\n'.join(lines)
