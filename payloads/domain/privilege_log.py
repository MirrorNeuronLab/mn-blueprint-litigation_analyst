"""Create a separate counsel-only worksheet using explicitly supplied descriptive metadata."""
from pathlib import Path

from mn_web_report_skill import render_document

FIELDS = ('reference', 'date', 'participants', 'document_type', 'description', 'basis', 'reviewer')


def publish(root, entries):
    data = [{**{key: row.get(key, '') for key in FIELDS}, 'approved': row.get('approved') is True}
            for row in entries]
    assets = Path(__file__).with_name('workspace_assets')
    html = render_document(title='Privilege log', identity='Counsel review',
        content_html='<main id="log"></main><p id="log-status" role="status"></p>',
        script=(assets / 'privilege.js').read_text(), style=(assets / 'casework.css').read_text(),
        data={'fields': FIELDS, 'rows': data}, data_id='log-data', max_bytes=4*1024*1024,
        description='Confidential working copy. Review the selected metadata before export.')
    path = 'case/privilege_log.html'
    (Path(root) / path).write_text(html, encoding='utf-8')
    return path
