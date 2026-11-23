"""Admit legal source dependencies and path exhibits as complete components."""
import json
from mn_context_engine_sdk.evidence import EvidenceGroup, admit_groups

from .temporal_evidence import VIEWS as TEMPORAL_VIEWS, path_evidence_ids


class IncompleteSupport(ValueError):
    """Cited passages cannot be reviewed with their required dependencies."""


def _identifiers(value):
    if not isinstance(value, list) or not all(isinstance(i, str) and i for i in value):
        return ()
    return tuple(dict.fromkeys(value))


def support_groups(result):
    """An unidentified dependency can affect any passage in its own observation."""
    groups = result.get('support_groups', [])
    if not isinstance(groups, list):
        groups = [None]
    for raw in groups:
        group = raw if isinstance(raw, dict) else {}
        raw_ids = group.get('source_evidence_ids')
        ids = _identifiers(raw_ids)
        required = group.get('required', False)
        complete = bool(ids) and group.get('complete') is True and type(required) is bool
        if not ids and raw_ids != []:
            ids = tuple(p['evidence_id'] for p in result.get('passages', [])
                        if isinstance(p, dict) and isinstance(p.get('evidence_id'), str))
        yield ids, complete, required is True


def _connected(seed, groups):
    selected = set(seed)
    while selected:
        size = len(selected)
        for ids in groups:
            if not selected.isdisjoint(ids):
                selected.update(ids)
        if len(selected) == size:
            break
    return selected


def _path_exhibits(result, groups, evidence):
    """Publish only matched paths with a complete group of verified originals."""
    candidates = result.get('paths', [])
    if not isinstance(candidates, list):
        return {}, 1
    if not candidates:
        return {}, 0
    eligible = {ids for ids, complete, _ in groups if complete and evidence.keys() >= set(ids)}
    exhibits, omitted = {}, 0
    for path in candidates:
        view = result.get('view')
        if isinstance(view, str) and view in TEMPORAL_VIEWS:
            ids = path_evidence_ids(path, evidence)
        else:
            ids = _identifiers(path.get('source_evidence_ids')) if isinstance(path, dict) else ()
        if not ids or ids not in eligible:
            omitted += 1
            continue
        exhibits.setdefault(ids, []).append({**path, 'source_evidence_ids': list(ids)})
    return exhibits, omitted


def assess_admitted(packet, records):
    from mn_context_engine_sdk.evidence import ContextRequirements, assess_context
    gaps = [gap for r in records if r['purpose'] in {'support','counter'}
            for gap in r['result'].get('unresolved', [])]
    attempted = any(r['result'].get('quality',{}).get('repair_attempted') for r in records)
    quality = assess_context(ContextRequirements(),has_evidence=bool(packet['evidence']),
        checks={'support_complete':not packet['support_admission']['unresolved_groups'],
                'capacity':packet['support_admission']['status'] not in {'insufficient_capacity','insufficient_budget'}},
        unresolved=gaps,repair_attempted=attempted).witness()
    if quality['action']=='repair':
        quality['action']='insufficient_evidence'
    return quality


def coverage(records, visible):
    return [{'purpose':r['purpose'], 'status':r['result'].get('status', 'unknown'),
             'exhaustive':r['result'].get('exhaustive', False),
             'unresolved':r['result'].get('unresolved', [])[:16],
             'unresolved_count':len(r['result'].get('unresolved', [])),
             'unresolved_details_omitted':max(0,len(r['result'].get('unresolved', []))-16),
             'passage_count':len(r['result'].get('passages', [])),
             'evidence_ids':[p['evidence_id'] for p in r['result'].get('passages', [])
                             if p['evidence_id'] in visible]} for r in records]


def review_closure(spans, records, cited):
    """Review the same complete dependency components as the assessor."""
    groups = [g for r in records for g in support_groups(r['result'])]
    selected = _connected(cited, [ids for ids, _, _ in groups])
    if any(not complete and not selected.isdisjoint(ids) for ids, complete, _ in groups):
        raise IncompleteSupport('Cited source has unresolved dependency support')
    if not selected <= {s['evidence_id'] for s in spans}:
        raise IncompleteSupport('Cited source dependency is unavailable for independent review')
    return [s for s in spans if s['evidence_id'] in selected]


def admit(spans, records, limit, *, fits_request=None):
    evidence = {s['evidence_id']:s for s in spans}
    valid, paths, blocked, bound = [], {}, set(), set()
    unresolved = unavailable_paths = 0
    for n, record in enumerate(records):
        result = record['result']
        dependencies = list(support_groups(result))
        exhibits, omitted = _path_exhibits(result, dependencies, evidence)
        unavailable_paths += omitted
        if type(result.get('unavailable_graph_paths')) is int:
            unavailable_paths += max(0, result['unavailable_graph_paths'])
        for index, (aliases, complete, required) in enumerate(dependencies):
            key = f'{n}:{index}'
            bound.update(aliases)
            if not complete or not set(aliases) <= evidence.keys():
                unresolved += 1
                blocked.update(aliases)
                continue
            matching = exhibits.pop(aliases, [])
            if matching:
                paths[key] = {'view':result.get('view'), 'paths':matching,
                              'status':result.get('status', 'unknown'), 'unresolved':result.get('unresolved', [])}
            valid.append((key, aliases, required))
    blocked = _connected(blocked, [ids for _, ids, _ in valid])
    groups = [EvidenceGroup(key, (key, *ids), required) for key, ids, required in valid if blocked.isdisjoint(ids)]
    unresolved += len(valid) - len(groups)
    path_coverage = {'unavailable_graph_paths': unavailable_paths} if unavailable_paths else {}
    for alias in evidence:
        if alias not in bound:
            groups.append(EvidenceGroup('source:'+alias, (alias,)))
    # Respect caller ranking across searches. Reserve duplicate collection copies
    # for after distinct content, without changing any source identity or closure.
    ranks = {key:n for n, key in enumerate(evidence)}
    groups.sort(key=lambda g: min(ranks[key] for key in g.members if key in ranks))
    seen, first, copies = set(), [], []
    for group in groups:
        basis = frozenset((e.get('content_sha256', key), e.get('start_offset'), e.get('end_offset'))
                          for key in group.members if (e := evidence.get(key)))
        (copies if basis in seen else first).append(group)
        seen.add(basis)
    groups = first + copies
    by_id = {g.group_id:g for g in groups}
    def render(selected):
        allowed = {m for key in selected for m in by_id[key].members if m in evidence}
        return {'evidence':[e for key,e in evidence.items() if key in allowed],
                'graph_paths':[paths[key] for key in selected if key in paths],
                'support_admission':{'status':'incomplete' if unresolved or unavailable_paths or len(selected)<len(groups) else 'complete',
                    'unresolved_groups':unresolved, 'omitted_groups':len(groups)-len(selected), **path_coverage}}
    def measure(packet):
        size = len(json.dumps(packet).encode())
        if size > limit or (fits_request is not None and not fits_request(packet)):
            return max(1, limit) + 1
        return size
    outcome = admit_groups(groups, render, measure=measure, limit=max(1,limit))
    return outcome.rendered or {'evidence':[], 'graph_paths':[], 'support_admission':{
        'status':outcome.status, 'unresolved_groups':unresolved, 'omitted_groups':len(groups), **path_coverage}}
