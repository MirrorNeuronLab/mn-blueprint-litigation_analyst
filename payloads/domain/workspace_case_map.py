"""Project source-backed records and draft citation roles into the case graph."""

from collections import defaultdict
import hashlib


RECORD_LIMIT = 60
HEADER_ADDRESS_LIMIT = 20


def case_map(workspace, *, for_display=True):
    """Keep observed headers, counsel annotations and model citation roles distinct."""
    nodes, edges = {}, []
    sources = {s['source_id']: s for s in workspace['sources']}
    evidence = {p['evidence_id']: p for p in workspace['evidence']}
    events = workspace['temporal']['events']
    visible_events = events[:RECORD_LIMIT] if for_display else events
    addresses = {n['id']: n for n in workspace['temporal']['nodes']}
    communications = defaultdict(list)
    omitted_addresses = 0
    for event in visible_events:
        refs = [p['evidence_id'] for p in event['evidence_refs']]
        nodes[event['id']] = {'id': event['id'], 'label': event['title'], 'kind': 'communication',
            'detail': sources[event['source_ids'][0]]['relative_path'],
            'date': event['time']['earliest'], 'date_label': event['display'], 'evidence_ids': refs,
            'qualification': event['qualification'], 'source_ids': event['source_ids'],
            'occurrence_id': event.get('metric_occurrence_id')}
        for source_id in event['source_ids']:
            communications[source_id].append(event)
        for field, recipients in event['fields']['headers'].items():
            visible_addresses = recipients[:HEADER_ADDRESS_LIMIT] if for_display else recipients
            omitted_addresses += len(recipients) - len(visible_addresses)
            for address in visible_addresses:
                original = addresses[address]
                node = nodes.setdefault(address, {'id': address, 'label': ' / '.join(original['names']) or address,
                    'detail': address, 'kind': 'correspondent', 'evidence_ids': [], 'source_ids': [],
                    'qualification': 'Names come from email headers. Identity remains unverified.'})
                node['evidence_ids'] = list(dict.fromkeys(node['evidence_ids'] + refs))
                node['source_ids'] = list(dict.fromkeys(node['source_ids'] + event['source_ids']))
                sender = field == 'From'
                edges.append({'source': address if sender else event['id'],
                    'target': event['id'] if sender else address, 'label': field + ' header',
                    'evidence_ids': refs, 'qualification': event['qualification']})

    issues = {issue['id']: issue for issue in workspace.get('counsel_issues', [])}
    findings = workspace['findings']
    review = workspace.get('reading_review') or workspace.get('consistency', {})
    blocked = set(review.get('withheld_finding_ids', []))
    for finding in findings:
        if finding['id'] in blocked:
            continue
        link_finding(nodes, edges, finding, sources, evidence, communications, issues)

    book = workspace.get('casework', {})
    for element in book.get('elements', []):
        nodes['element:' + element['id']] = {'id': 'element:' + element['id'], 'kind': 'element',
            'label': element['title'], 'detail': element['group'], 'evidence_ids': [], 'source_ids': [],
            'qualification': 'Element defined by counsel. An empty element remains an open proof question.'}
    for fact in book.get('facts', []):
        eid = 'clip-' + fact['id']
        if fact.get('binding') != 'current' or eid not in evidence:
            continue
        sid = fact['anchor']['source']
        key = 'fact:' + fact['id']
        nodes[key] = {'id': key, 'kind': 'fact', 'label': fact['wording'], 'detail': fact['actor'],
                      'source_ids': [sid], 'evidence_ids': [eid], 'qualification': 'Counsel-authored proposition.'}
        edges.append({'source': key, 'target': add_document(nodes, sources[sid]), 'label': 'Quoted passage',
                      'evidence_ids': [eid], 'qualification': 'Exact selection in the verified source version.'})
        element = nodes.get('element:' + fact['element'])
        if element:
            element['evidence_ids'].append(eid)
            element['source_ids'] = list(dict.fromkeys([*element['source_ids'], sid]))
            edges.append({'source': element['id'], 'target': key, 'label': 'Element ' + fact['role'].lower(),
                          'evidence_ids': [eid], 'kind': {'Support':'support','Contrary':'contrary'}.get(fact['role'], 'context'),
                          'qualification': 'Proof role assigned by counsel.'})
    reversed_links = {a['reverses'] for a in book.get('aliases', []) if a['reverses']}
    for alias in book.get('aliases', []):
        fact_node = nodes.get('fact:' + alias['fact'])
        if alias['reverses'] or alias['id'] in reversed_links or not fact_node:
            continue
        common = {'detail': alias['actor'], 'evidence_ids': fact_node['evidence_ids'], 'source_ids': fact_node['source_ids'],
                  'qualification': 'Identity link confirmed by counsel from this passage.'}
        for kind in ('alias', 'person'):
            key = kind + ':' + alias['id']
            nodes[key] = {**common, 'id': key, 'kind': kind, 'label': alias[kind]}
        edges.append({**common, 'source': 'alias:' + alias['id'], 'target': 'person:' + alias['id'], 'label': 'Confirmed identity'})

    financial = workspace.get('financial_review', {}).get('events', [])
    visible_financial = financial[:RECORD_LIMIT] if for_display else financial
    for record in visible_financial:
        key = 'record:' + hashlib.sha256('|'.join(str(record[k]) for k in
            ('transaction_ref', 'currency', 'ledger_id', 'record_id')).encode()).hexdigest()[:20]
        transaction = 'transaction:' + record['transaction_ref']
        node = nodes.setdefault(transaction, {'id': transaction, 'label': record['transaction_ref'],
            'kind': 'transaction', 'evidence_ids': [], 'source_ids': [],
            'qualification': 'These records use the same reference. External payment and settlement remain unverified.'})
        node['evidence_ids'] = list(dict.fromkeys(node['evidence_ids'] + record['evidence_ids']))
        node['source_ids'] = list(dict.fromkeys(node['source_ids'] + [record['source_id']]))
        nodes[key] = {'id': key, 'label': record['event_type'].replace('_', ' ').capitalize() + ' · ' + record['currency'] + ' ' + record['amount'],
            'kind': 'financial_record', 'date': record.get('event_date'), 'date_label': record['date_basis'],
            'evidence_ids': record['evidence_ids'], 'source_ids': [record['source_id']],
            'qualification': record['classification_basis']}
        edges.append({'source': key, 'target': transaction, 'label': 'Recorded reference',
            'evidence_ids': record['evidence_ids'], 'qualification': node['qualification']})
        source_id = record['source_id']
        for event in communications.get(source_id, ()):
            edges.append({'source': event['id'], 'target': key, 'label': 'Same source',
                'evidence_ids': list(dict.fromkeys(record['evidence_ids'] + [p['evidence_id'] for p in event['evidence_refs']])),
                'qualification': 'Both records come from this source. Participation and payment remain unverified.'})
        document_id = 'document:' + source_id
        if document_id in nodes:
            edges.append({'source': key, 'target': document_id, 'label': 'Recorded in document',
                'evidence_ids': record['evidence_ids'], 'qualification': record['classification_basis']})

    omitted_documents = 0
    if not nodes:
        # A document-only review can still open its sources without inventing links.
        for source_id in list(sources)[:RECORD_LIMIT]:
            add_document(nodes, sources[source_id])
        omitted_documents = max(0, len(sources) - RECORD_LIMIT)
    return {'nodes': list(nodes.values()), 'edges': edges,
        'omitted_communications': len(events) - len(visible_events),
        'omitted_financial_records': len(financial) - len(visible_financial),
        'omitted_header_addresses': omitted_addresses, 'omitted_documents': omitted_documents,
        'definition': 'Explore recorded relationships and the passages cited by draft findings. Identity, causation and liability require separate evidence.'}


def add_document(nodes, source):
    source_id = source['source_id']
    key = 'document:' + source_id
    nodes.setdefault(key, {'id': key, 'label': source['relative_path'], 'kind': 'document',
        'source_ids': [source_id], 'evidence_ids': [], 'qualification': source.get('extraction_status', '')})
    return key


def link_finding(nodes, edges, finding, sources, evidence, communications, issues):
    contrary = set(finding.get('counter_evidence', []))
    citations = list(dict.fromkeys(finding.get('counter_evidence', []) + finding.get('supporting_evidence', [])))
    if not citations or any(i not in evidence or evidence[i]['source_id'] not in sources for i in citations):
        return
    grouped = defaultdict(list)
    for identifier in citations:
        grouped[(evidence[identifier]['source_id'], identifier in contrary)].append(identifier)
    nodes[finding['id']] = {'id': finding['id'], 'label': finding['title'], 'kind': 'finding',
        'detail': finding.get('review_state'),
        'source_ids': list(dict.fromkeys(source_id for source_id, _ in grouped)), 'evidence_ids': citations,
        'qualification': 'Draft assessment. Review the exact passages and their context with counsel.'}
    for (source_id, is_contrary), ids in grouped.items():
        records = communications.get(source_id, ())
        target = records[0]['id'] if len(records) == 1 else add_document(nodes, sources[source_id])
        edges.append({'source': finding['id'], 'target': target,
            'label': 'Contrary citation' if is_contrary else 'Supporting citation',
            'kind': 'contrary' if is_contrary else 'support', 'evidence_ids': ids,
            'qualification': 'Citation role assigned in the draft review.'})
    for issue_id in finding.get('counsel_issue_ids', []):
        issue = issues[issue_id]
        key = 'issue:' + issue_id
        node = nodes.setdefault(key, {'id': key, 'label': issue['question'], 'kind': 'issue',
            'evidence_ids': [], 'source_ids': [], 'qualification': issue['framework_basis']})
        node['evidence_ids'] = list(dict.fromkeys(node['evidence_ids'] + citations))
        node['source_ids'] = list(dict.fromkeys(node['source_ids'] + [source_id for source_id, _ in grouped]))
        edges.append({'source': key, 'target': finding['id'], 'label': 'Examined in draft',
            'evidence_ids': citations, 'qualification': 'This draft addresses a question supplied by counsel.'})
