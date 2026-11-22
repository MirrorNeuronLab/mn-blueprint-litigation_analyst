"""Build the offline review index from the same authorized DuckDB snapshot as the graph."""

from calendar import monthrange
from datetime import date
import hashlib
import re

from .case_ontology import write_rows, rows

MONTHS = "January February March April May June July August September October November December".split()
MONTH = "|".join(MONTHS)
DATE = re.compile(rf"\b(?:(?P<iso>\d{{4}}-\d{{2}}-\d{{2}})|(?P<part>early |mid[- ]|late )?(?P<month>{MONTH})"
                  r"\s*(?:(?P<day>\d{1,2})(?:st|nd|rd|th)?\b,?\s*)?(?P<year>\d{4})?)\b", re.I)
SCHEMA = """
CREATE TABLE review_units (
    id VARCHAR PRIMARY KEY, source_id VARCHAR, start_char BIGINT, end_char BIGINT);
CREATE TABLE review_dates (
    unit_id VARCHAR, start_char BIGINT, end_char BIGINT, wording VARCHAR,
    earliest VARCHAR, latest VARCHAR, meaning VARCHAR, lane VARCHAR);
CREATE TABLE graph_node_sources (node_id VARCHAR, source_id VARCHAR);
CREATE TABLE proof_elements (id VARCHAR PRIMARY KEY, claim_name VARCHAR, element VARCHAR, kind VARCHAR);
CREATE TABLE reviewed_facts (
    id VARCHAR PRIMARY KEY, element_id VARCHAR, role VARCHAR, wording VARCHAR, reviewer VARCHAR,
    source_id VARCHAR, source_hash VARCHAR, start_char BIGINT, end_char BIGINT);
"""
# The file retains all records. Bound the extra offline HTML projection separately.
MAX_UNITS = 24000
MAX_LINKS = 16000


def date_window(match):
    if match['iso']:
        day = date.fromisoformat(match['iso']).isoformat()
        return day, day
    if not match['year']:
        return None, None
    year, month = int(match['year']), MONTHS.index(match['month'].capitalize()) + 1
    end = monthrange(year, month)[1]
    if match['day']:
        start = end = int(match['day'])
    else:
        start, end = {'early': (1, 10), 'mid': (11, 20), 'late': (21, end)}.get(
            (match['part'] or '').strip(' -').lower(), (1, end))
    return date(year, month, start).isoformat(), date(year, month, end).isoformat()


def dated_mentions(line, start):
    # A date in a quotation describes what that source says. Labels are navigation only.
    for match in DATE.finditer(line):
        if not (match['iso'] or match['day'] or match['year'] or match['part']):
            continue
        try:
            earliest, latest = date_window(match)
        except (ValueError, OverflowError):
            continue
        prefix = line[:match.start()].lower()
        # Use the nearest explicit cue within this clause, not the title of the whole file.
        cues = list(re.finditer(r"\b(termination(?: +date)?|terminat(?:ed|es)|effective|"
                               r"deposition|testif(?:ied|ying)|testimony|hearing|"
                               r"acknowledged|received|receipt|sent|signed|meeting|met|posted|reversed)\b", prefix))
        cue = cues[-1].group() if cues and not re.search(r'[.;!?]', prefix[cues[-1].end():]) else ''
        if re.fullmatch(r'\s*(?:document |record )?date\s*:\s*', prefix):
            meaning, lane = 'Record date', 'Business record'
        elif cue.startswith('terminat') or (cue == 'effective' and re.search(r'terminat\w*[^.;!?]{0,55}$', prefix)):
            meaning, lane = 'Termination', 'Contract or notice'
        elif cue in ('deposition', 'testified', 'testifying', 'testimony', 'hearing'):
            meaning, lane = 'Testimony given', 'Testimony'
        elif cue in ('received', 'receipt', 'acknowledged', 'sent'):
            meaning, lane = cue.capitalize(), 'Notice or communication'
        elif cue in ('signed', 'effective'):
            meaning, lane = cue.capitalize(), 'Contract or notice'
        elif cue in ('posted', 'reversed'):
            meaning, lane = cue.capitalize(), 'Business record'
        else:
            meaning, lane = ('Meeting described' if cue in ('meeting', 'met') else 'Date mentioned'), 'Reported event'
        yield start + match.start(), start + match.end(), match.group().strip(), earliest, latest, meaning, lane


def source_units(sources):
    for source in sources:
        text = source.get('text')
        if not text:
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        if digest != source['content_sha256']:
            raise ValueError('Case question index source hash mismatch')
        sid = source['source_id']
        # Offsets are Unicode code points in exactly the held text. Split long unbroken lines too.
        for line in re.finditer(r'[^\r\n]+', text):
            for start in range(line.start(), line.end(), 1500):
                end = min(start + 1500, line.end())
                body = text[start:end]
                if body.strip():
                    key = hashlib.sha256(f'{sid}\0{digest}\0{start}\0{end}'.encode()).hexdigest()[:24]
                    yield ('u-' + key, sid, start, end), body


def populate(db, workspace, nodes):
    db.execute(SCHEMA)
    units, dates = [], []
    for row, body in source_units(workspace['sources']):
        units.append(row)
        dates.extend((row[0], *d) for d in dated_mentions(body, row[2]))
        if len(units) >= 1024:
            write_rows(db, 'review_units', units)
            write_rows(db, 'review_dates', dates)
            units, dates = [], []
    write_rows(db, 'review_units', units)
    write_rows(db, 'review_dates', dates)
    write_rows(db, 'graph_node_sources', [(n['id'], s) for n in nodes.values() for s in n.get('source_ids', [])])
    book = workspace.get('casework', {})
    write_rows(db, 'proof_elements', [(x['id'], x['group'], x['title'], x['kind']) for x in book.get('elements', [])])
    write_rows(db, 'reviewed_facts', [
        (f['id'], f['element'], f['role'], f['wording'], f['actor'], a['source'], a['hash'], a['start'], a['end'])
        for f in book.get('facts', []) if (a := f['anchor']) and f.get('binding') == 'current'])


def offline_index(db, workspace):
    """Read DuckDB, preserving qualified roles and source IDs. Text already lives in the report."""
    units = rows(db, """SELECT id, source_id, start_char, end_char FROM review_units
        ORDER BY row_number() OVER (PARTITION BY source_id ORDER BY start_char), source_id LIMIT ?""", [MAX_UNITS])
    identifiers = [u['id'] for u in units]
    dates = rows(db, """SELECT unit_id, wording, earliest, latest, meaning, lane FROM review_dates
        WHERE unit_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY unit_id, start_char""", [identifiers])
    links = rows(db, """SELECT e.relation, a.label AS origin, b.label AS target, c.passage_id
        FROM graph_edges e JOIN graph_nodes a ON a.id=e.source JOIN graph_nodes b ON b.id=e.target
        JOIN graph_citations c ON e.id=c.edge_id ORDER BY e.id, c.passage_id LIMIT ?""", [MAX_LINKS])
    return {'snapshot': workspace['snapshot_id'], 'units': [[u[k] for k in ('id','source_id','start_char','end_char')] for u in units],
            'dates': dates, 'links': links, 'total_units': db.execute('SELECT count(*) FROM review_units').fetchone()[0],
            'total_links': db.execute('SELECT count(*) FROM graph_citations').fetchone()[0]}
