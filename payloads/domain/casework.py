"""Validate counsel's portable review work separately from findings and source evidence."""
from datetime import date
import re

from jsonschema import Draft202012Validator
from mn_temporal_graph_skill import fingerprint

VERSION = 'mn.litigation.casework.v1'
TEXT = {'type': 'string', 'maxLength': 4000}
NAME = {'type': 'string', 'minLength': 1, 'maxLength': 500}
ID = {'type': 'string', 'pattern': '^[a-zA-Z0-9_-]{1,100}$'}
SOURCE_ID = {'type': 'string', 'minLength': 1, 'maxLength': 8192}
SHA = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
REF = {'type': 'string', 'maxLength': 100}
BOOL = {'type': 'boolean'}
SOURCE_VERSIONS = {'type': 'object', 'maxProperties': 20000, 'propertyNames': SOURCE_ID, 'additionalProperties': SHA}


def record(fields, optional=()):
    return {'type': 'object', 'additionalProperties': False, 'properties': fields,
            'required': [k for k in fields if k not in optional]}


def choice(*values):
    return {'enum': list(values)}


ANCHOR = record({'source': SOURCE_ID, 'hash': SHA, 'start': {'type': 'integer', 'minimum': 0},
                 'end': {'type': 'integer', 'minimum': 1}, 'quote': TEXT, 'pin': TEXT})
MODELS = {
    'elements': record({'id': ID, 'group': NAME, 'title': NAME, 'kind': choice('Claim','Defense','Issue')}),
    'facts': record({'id': ID, 'element': REF, 'role': choice('Support','Contrary','Context'),
                     'wording': TEXT, 'actor': NAME, 'witness': TEXT, 'approved': BOOL,
                     'anchor': ANCHOR, 'binding': choice('current','changed'), 'reviewed_snapshot': NAME,
                     'checked_versions': SOURCE_VERSIONS}, ('binding','reviewed_snapshot','checked_versions')),
    'outlines': record({'id': ID, 'element': ID, 'witness': NAME, 'statement': ID, 'exhibit': ID,
                        'question': TEXT, 'resolution': TEXT, 'checked_versions': SOURCE_VERSIONS}, ('checked_versions',)),
    'tasks': record({'id': ID, 'element': REF, 'origin': TEXT, 'record': NAME, 'closure': TEXT,
                     'owner': NAME, 'target': TEXT, 'closing_fact': REF, 'resolution': TEXT, 'closed_by': TEXT}),
    'aliases': record({'id': ID, 'person': NAME, 'alias': NAME, 'fact': ID, 'actor': NAME,
                       'at': NAME, 'reverses': REF}),
    'queries': record({'id': ID, 'chain': {'type':'array','minItems':1,'maxItems':8,'items':NAME}}),
    'events': record({'id': ID, 'fact': ID, 'label': NAME, 'lane': choice('Contract','Notice','Testimony','Business record','Reported event'),
                      'meaning': choice('Record date','Reported event','Termination','Testimony given'),
                      'when': NAME, 'from': TEXT, 'to': TEXT}),
}
BOOK_SCHEMA = record({'version': {'const': VERSION}, 'matter': NAME, 'scope': NAME, 'snapshot': NAME,
                      'versions': SOURCE_VERSIONS,
                      'pending_sources': {'type':'array','uniqueItems':True,'maxItems':20000,'items':SOURCE_ID},
                      **{key:{'type':'array','maxItems':500,'items':model} for key, model in MODELS.items()}},
                     ('pending_sources',))
VALIDATE = Draft202012Validator(BOOK_SCHEMA)


def fresh(workspace):
    return {'version': VERSION, 'matter': workspace['matter_id'], 'scope': workspace['access_scope'],
            'snapshot': workspace['snapshot_id'],
            'versions': {s['source_id']: s['content_sha256'] for s in workspace['sources']},
            **{k: [] for k in MODELS}}


def changed_sources(versions, previous):
    old_hashes = set(previous.values())
    return {sid for sid, sha in versions.items() if previous and previous.get(sid) != sha and sha not in old_hashes}


def prepare(workspace, prior=None):
    book = fresh(workspace)
    sources = {s['source_id']: s for s in workspace['sources']}
    previous_versions = {}
    pending = set()
    if prior is not None:
        VALIDATE.validate(prior)
        if prior['matter'] != book['matter'] or prior['scope'] != book['scope']:
            raise ValueError('Saved review belongs to a different matter or access scope')
        if prior['versions'].keys() <= sources.keys():
            previous_versions = prior['versions']
            pending.update(s for s in prior.get('pending_sources', []) if s in sources)
            for key in MODELS:
                items = [dict(item) for item in prior[key]]
                if len({r['id'] for r in items}) != len(items):
                    raise ValueError('Duplicate casework record identifier')
                book[key] = items
            for fact in book['facts']:
                a = fact['anchor']
                source = sources.get(a['source'])
                if not source or a['source'] not in previous_versions or not a['quote'] or a['end'] - a['start'] != len(a['quote']):
                    raise ValueError('Invalid saved fact source or character range')
                if a['hash'] == source['content_sha256']:
                    if (source['text'] or '')[a['start']:a['end']] != a['quote']:
                        raise ValueError('Saved quotation differs from its source version')
                    fact['binding'] = 'current'
                else:
                    if a['hash'] != previous_versions[a['source']] and fact.get('binding') != 'changed':
                        raise ValueError('Historical quotation has no matching saved source version')
                    # Retain the self-attributed historical excerpt; never use it as current evidence.
                    fact.update(binding='changed', approved=False)
            validate_links(book)
        else:
            workspace['casework_import_note'] = 'Prior review work was withheld because its source scope is no longer available.'
    existing = {x['id'] for x in book['elements']}
    for issue in workspace.get('counsel_issues', []):
        for title in issue.get('elements', []):
            key = 'el-' + fingerprint([issue['id'], title])[:20]
            if key not in existing:
                book['elements'].append({'id': key, 'group': issue['question'], 'title': title,
                                         'kind': issue.get('kind','Issue')})
                existing.add(key)
    workspace['casework'] = book
    workspace.setdefault('capabilities', {}).update(
        legal_elements='Define claims, defenses and required proof in the proof chart.',
        identity_corrections='Review and reverse source-linked aliases within this matter.')
    spans = {p['evidence_id']: p for p in workspace.get('evidence', [])}
    for fact in book['facts']:
        if fact['binding'] == 'current':
            a = fact['anchor']
            key = 'clip-' + fact['id']
            spans[key] = {'evidence_id': key, 'source_id': a['source'], 'content_sha256': a['hash'],
                          'start_offset': a['start'], 'end_offset': a['end'], 'text': a['quote'],
                          'provenance_kind': 'Counsel-selected source passage'}
    workspace['evidence'] = list(spans.values())
    pending.update(changed_sources(book['versions'], previous_versions))
    book['pending_sources'] = sorted(pending)
    workspace['casework_changed_sources'] = book['pending_sources']
    return book


def validate_links(book):
    elements = {x['id'] for x in book['elements']}
    facts = {x['id']: x for x in book['facts']}
    for item in book['facts'] + book['tasks'] + book['outlines']:
        if item['element'] and item['element'] not in elements:
            raise ValueError('Unknown proof element')
    for item in book['outlines']:
        if item['statement'] not in facts or item['exhibit'] not in facts or item['statement'] == item['exhibit']:
            raise ValueError('A witness comparison requires two different facts')
    previous, active = {}, {}
    for link in book['aliases']:
        if link['fact'] not in facts or (link['reverses'] and link['reverses'] not in previous):
            raise ValueError('Unknown identity evidence or prior decision')
        if link['reverses'] and any(link[k] != previous[link['reverses']][k] for k in ('person','alias','fact')):
            raise ValueError('Identity reversal differs from original link')
        quote = facts[link['fact']]['anchor']['quote'].casefold()
        if not link['reverses'] and any(not re.search(r'(?<!\w)' + re.escape(link[k].casefold()) + r'(?!\w)', quote)
                                        for k in ('alias','person')):
            raise ValueError('Identity link requires a quotation containing both names or identifiers')
        key = link['alias'].casefold()
        if link['reverses']:
            if active.pop(key, None) != link['reverses']:
                raise ValueError('Identity reversal must name the active confirmation')
        elif key in active:
            raise ValueError('Reverse an active alias before reassigning it')
        else:
            active[key] = link['id']
        previous[link['id']] = link
    for item in book['tasks']:
        if item['target']:
            date.fromisoformat(item['target'])
        if item['closing_fact'] and (item['closing_fact'] not in facts or not item['closed_by'] or not item['resolution']):
            raise ValueError('Closing a task requires a cited fact and a reviewed resolution')
    for item in book['events']:
        if item['fact'] not in facts:
            raise ValueError('Unknown chronology fact')
        for day in (item['from'], item['to']):
            if day:
                date.fromisoformat(day)
        if bool(item['from']) != bool(item['to']) or item['from'] and item['from'] > item['to']:
            raise ValueError('Event end precedes start')
