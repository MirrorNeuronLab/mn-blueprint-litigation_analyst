"""Translate bounded natural-language questions into read-only case graph queries."""

import hashlib
import json
from pathlib import Path
import re

from mn_graph_analysis_skill import TraversalPlan, traverse

from .case_ontology import EDGE_ROWS, PATH, RELATION_CODES, VERSION, connect, passage_refs, rows


QUESTION_PATTERNS = (
    (r'(?:what (?:evidence |facts? )?supports?|which facts support) (?:the )?(?:proof )?element (.+)',
     'element', ('SUPPORTED_BY_FACT',)),
    (r'(?:what (?:evidence |facts? )?contradicts?|which facts contradict) (?:the )?(?:proof )?element (.+)',
     'element', ('CONTESTED_BY_FACT',)),
    (r'(?:what (?:evidence )?(?:supports|corroborates)|which (?:documents|passages) support|show supporting (?:evidence|sources) for) (.+)',
     'finding', ('CITES_IN_SUPPORT',)),
    (r'(?:what (?:evidence )?(?:contradicts|challenges|opposes)|which (?:documents|passages) contradict|show contrary (?:evidence|sources) for) (.+)',
     'finding', ('CITES_IN_CONFLICT',)),
    (r'(?:which|what) (?:records|entries) (?:reference|mention|refer to) (.+)',
     'transaction', ('REFERENCES_TRANSACTION',)),
    (r'who sent (.+)', 'communication', ('FROM_HEADER',)),
    (r'who (?:received|was addressed on) (.+)', 'communication', ('TO_HEADER', 'CC_HEADER', 'BCC_HEADER')),
    (r'(?:what|who) (?:is |was )?(?:connected|linked) to (.+)', '', RELATION_CODES),
)
PATH_QUESTION = re.compile(r'how (?:is|does) (.+?) (?:connected to|connect to|related to|relate to) (.+)', re.I)
GUIDANCE = ('Ask what supports or contradicts a named draft finding or proof element, who sent a named email, '
            'which records reference a transaction, or how two graph objects connect.')
LIMITATION = ('Results cover the saved authorized graph. Draft citations and recorded relationships retain their original qualifications.')


def open_graph(run_dir):
    root = Path(run_dir)
    path = root / PATH
    index = root / 'review_index.json'
    if path.parent.is_symlink() or path.is_symlink() or index.is_symlink():
        raise ValueError('Case graph files must be regular run artifacts')
    receipt = json.loads(index.read_text(encoding='utf-8')).get('case_ontology')
    if not receipt or not path.is_file() or receipt.get('version') != VERSION or receipt.get('path') != PATH:
        raise ValueError('This run has no published case ontology')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != receipt.get('sha256'):
            raise ValueError('Case graph integrity check failed')
    return connect(path, read_only=True)


def resolve(database, phrase, kind=''):
    name = re.sub(r'^the (?:draft |email |transaction )?(?:finding|message|email|transaction)(?: (?:about|on))? ',
                  '', phrase.strip(), flags=re.I).strip(' "“”\'')
    if not name:
        return []
    matches = rows(database, '''
        SELECT id, label, kind, detail, (lower(id) = lower(?) OR lower(label) = lower(?)
            OR lower(detail) = lower(?)) IS TRUE AS exact
        FROM graph_nodes WHERE (? = '' OR kind = ?)
          AND (lower(id) = lower(?) OR contains(lower(label), lower(?)) OR contains(lower(detail), lower(?)))
        ORDER BY exact DESC, label, id LIMIT 8
    ''', [name, name, name, kind, kind, name, name, name])
    return [node for node in matches if node['exact']] if matches and matches[0]['exact'] else matches


def adjacency(database, seeds, relations, limit):
    return rows(database, EDGE_ROWS + '''
        WHERE e.relation IN (SELECT unnest(?::VARCHAR[])) AND
            (e.source IN (SELECT unnest(?::VARCHAR[])) OR e.target IN (SELECT unnest(?::VARCHAR[])))
        ORDER BY e.relation, a.label, b.label, e.id LIMIT ?
    ''', [list(relations), list(seeds), list(seeds), limit])


def query(database, question):
    if not isinstance(question, str) or not question.strip() or len(question) > 480:
        raise ValueError('Enter a case question of up to 480 characters')
    question = ' '.join(question.split()).rstrip('?. ')
    path = PATH_QUESTION.fullmatch(question)
    if path:
        lookup = [(path[1], ''), (path[2], '')]
        relations = RELATION_CODES
    else:
        for pattern, kind, relations in QUESTION_PATTERNS:
            match = re.fullmatch(pattern, question, re.I)
            if match:
                lookup = [(match[1], kind)]
                break
        else:
            return {'status': 'unsupported_question', 'summary': GUIDANCE}

    entities = []
    for phrase, kind in lookup:
        candidates = resolve(database, phrase, kind)
        if len(candidates) != 1:
            return {'status': 'ambiguous' if candidates else 'unresolved',
                    'summary': 'Choose a more specific graph object.' if candidates else 'No matching object in the saved case graph.',
                    'candidates': [{k: n[k] for k in ('id', 'label', 'kind', 'detail')} for n in candidates]}
        entities.append(candidates[0]['id'])

    if path:
        if entities[0] == entities[1]:
            return {'status': 'same_object', 'summary': 'Both names match the same graph object.'}

        def fetch(frontier, kinds, _direction, limit):
            found = adjacency(database, frontier, kinds, limit)
            return {'edges': found[:limit - 1], 'complete': len(found) < limit, 'unresolved': []}

        walked = traverse(TraversalPlan((entities[0],), relations, direction='both', target=entities[1],
                                        max_hops=4, max_nodes=80, max_edges=49), fetch)
        matches = next((item['edges'] for item in walked['paths'] if item['target'] == entities[1]), [])
        if not matches:
            return {'status': walked['status'], 'summary': 'No connection found within the searched four-hop scope.',
                    'limits': walked['unresolved']}
        truncated = False
    else:
        matches = adjacency(database, entities, relations, 13)
        truncated = len(matches) > 12
        matches = matches[:12]
    references = passage_refs(database, [match['id'] for match in matches], per_edge=3)
    for match in matches:
        citations = [ref for ref in references if ref['edge_id'] == match['id']]
        if not citations:
            raise ValueError('Case graph relationship has no source passage')
        match['passages'] = [{k: v for k, v in ref.items() if k not in {'edge_id', 'passage_count'}}
                             for ref in citations]
        truncated |= citations[0]['passage_count'] > len(citations)
    return {'status': 'matched' if matches else 'no_match', 'relationships': matches,
            'summary': LIMITATION if matches else 'No matching relationships in the saved case graph.',
            'truncated': truncated}
