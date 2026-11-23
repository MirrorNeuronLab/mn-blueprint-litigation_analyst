"""Short request-local citation keys with a durable, exact source cross-reference."""
from copy import deepcopy
from .app.findings import CITATION_BYTE_LIMIT


def keys_for(identifiers):
    return {eid: f'E{n}' for n, eid in enumerate(identifiers, 1)}


def finding_citations(sizes):
    """Every permitted list fits the total citation limit, including mixed-size pairs."""
    def array(pool, maximum):
        return {'type': 'array', 'minItems': 1, 'maxItems': min(40, maximum),
                'items': {'enum': list(pool)}}

    if sum(sizes.values()) <= CITATION_BYTE_LIMIT:
        return array(sizes, len(sizes))
    # A legal pair contains at most one passage over half the allowance. Keep
    # that passage selectable alongside any short passage that fits with it.
    choices = [array(sizes, 1)]
    short = {k: size for k, size in sizes.items() if 2 * size <= CITATION_BYTE_LIMIT}
    if len(short) >= 2:
        total, maximum = 0, 0
        for size in sorted(short.values(), reverse=True):
            if total + size > CITATION_BYTE_LIMIT:
                break
            total += size
            maximum += 1
        choices.append(array(short, maximum))
        # Allow three short source excerpts even if other candidates approach
        # half the allowance. Each cited account may support a different fact.
        thirds = [k for k, size in short.items() if 3 * size <= CITATION_BYTE_LIMIT]
        if maximum < 3 and len(thirds) >= 3:
            choices.append(array(thirds, 3))
    for key, size in sizes.items():
        if key in short:
            continue
        partners = [k for k, other in short.items() if size + other <= CITATION_BYTE_LIMIT]
        if partners:
            choices.append(array([key, *partners], 2))
    return choices[0] if len(choices) == 1 else {'anyOf': choices}


def encode(data, schema):
    passages = data.get('evidence', [])
    if not passages or 'passage' not in schema.get('$defs', {}):
        return data, schema, {}
    keys = keys_for(p['evidence_id'] for p in passages)
    sources = {}
    evidence = []
    for p in passages:
        source = p['source_id']
        sources[source] = p['content_sha256']
        evidence.append({'evidence_id': keys[p['evidence_id']], 'ledger_id': p['evidence_id'],
                         'source_id': source, 'span': [p['start_offset'], p['end_offset']], 'text': p['text']})

    def references(row, field):
        return {**row, field: [keys[i] for i in row[field]]}

    financial = data['verified_financial']
    request = {**data, 'evidence': evidence, 'normalized_source_hashes': sources,
        'search_coverage': [references(row, 'evidence_ids') for row in data['search_coverage']],
        'verified_financial': {**financial,
            'events': [references(row, 'evidence_ids') for row in financial['events']],
            'transactions': [references(row, 'evidence_ids') for row in financial['transactions']]},
        'graph_paths': [{**g, 'paths': [references(p, 'source_evidence_ids') for p in g['paths']]}
                        for g in data.get('graph_paths', [])]}
    grammar = deepcopy(schema)
    grammar['$defs']['passage']['enum'] = list(keys.values())
    finding = grammar['properties']['report']['properties']['findings']['items']['properties']
    eligible = set(finding['evidence_ids']['items'].get('enum', keys))
    sizes = {keys[p['evidence_id']]: len(p['text'].encode()) for p in passages
             if p['evidence_id'] in eligible and len(p['text'].encode()) <= CITATION_BYTE_LIMIT}
    if sizes:
        finding['evidence_ids'] = finding_citations(sizes)
    return request, grammar, {v: k for k, v in keys.items()}


def decode(value, ledger_ids):
    if not ledger_ids:
        return value
    result = deepcopy(value)
    hypothesis = result['hypothesis']
    for row, field in [(hypothesis, 'supporting_evidence'), (hypothesis, 'contradictory_evidence'),
                       *((f, 'evidence_ids') for f in result['report']['findings']),
                       *((w, 'evidence_ids') for w in result['work_items'])]:
        row[field] = list(dict.fromkeys(ledger_ids[key] for key in row[field]))
    return result
