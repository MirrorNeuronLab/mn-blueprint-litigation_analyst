import hashlib
import json
from pathlib import Path
import sys

import duckdb
import pytest


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'payloads'))
    from domain.case_ontology import PATH, publish

    (tmp_path / 'case').mkdir()
    documents = {
        'request': 'From: Maya Chen <maya@example.test>\nSubject: Transfer request',
        'ledger': 'Ledger reversal for TX-104',
    }
    sources = [{'source_id': key, 'relative_path': key + ('.eml' if key == 'request' else '.txt')}
               for key in documents]
    passages = [{'evidence_id': key + '-span', 'source_id': key, 'start_offset': 0, 'end_offset': len(text),
                 'content_sha256': hashlib.sha256(text.encode()).hexdigest()} for key, text in documents.items()]
    finding = {'id': 'F-approval', 'title': 'Authorization for transfer',
               'supporting_evidence': ['request-span', 'ledger-span'], 'counter_evidence': ['ledger-span']}
    workspace = {
        'snapshot_id': 'synthetic-graph', 'access_scope': 'case', 'sources': sources, 'evidence': passages,
        'findings': [finding, {**finding, 'id': 'withheld', 'title': 'Withheld draft'},
                     {**finding, 'id': 'missing', 'title': 'Privileged basis',
                      'supporting_evidence': ['restricted-span']}],
        'consistency': {'withheld_finding_ids': ['withheld']},
        'temporal': {'nodes': [{'id': 'maya@example.test', 'names': ['Maya Chen']}], 'events': [
            {'id': 'message', 'title': 'Transfer request', 'source_ids': ['request'],
             'time': {'earliest': None}, 'display': 'Date unresolved', 'qualification': 'Recorded addressing.',
             'evidence_refs': [passages[0]], 'fields': {'headers': {'From': ['maya@example.test']}}}]},
        'financial_review': {'events': [{'event_type': 'reversal', 'currency': 'USD', 'ledger_id': 'accounting',
            'amount': '8000.00', 'transaction_ref': 'TX-104', 'record_id': '1', 'date_basis': 'No date supplied',
            'evidence_ids': ['ledger-span'], 'classification_basis': 'Counsel annotation.', 'source_id': 'ledger'}]},
    }
    receipt = publish(tmp_path, workspace)
    receipt['sha256'] = hashlib.sha256((tmp_path / PATH).read_bytes()).hexdigest()
    (tmp_path / 'review_index.json').write_text(json.dumps({'case_ontology': receipt}))
    return tmp_path, workspace, receipt


def test_direct_queries_return_typed_relationships_and_passage_locations(archive):
    from domain.case_graph_query import open_graph, query
    from domain.case_ontology import appendix

    root, _, receipt = archive
    with open_graph(root) as database:
        result = query(database, 'What evidence contradicts the draft finding about authorization?')
        edge, = result['relationships']
        assert edge['relation'] == 'CITES_IN_CONFLICT'
        assert edge['provenance'] == 'draft_assessment'
        assert edge['passages'][0]['id'] == 'ledger-span'
        result = query(database, 'Which documents support authorization?')
        assert [p['id'] for r in result['relationships'] for p in r['passages']] == ['request-span']
        result = query(database, 'How is Maya Chen connected to ledger.txt?')
        assert [r['relation'] for r in result['relationships']] == [
            'FROM_HEADER', 'CITES_IN_SUPPORT', 'CITES_IN_CONFLICT']
        assert query(database, 'How is Maya Chen connected to TX-104?')['status'] == 'incomplete'
        assert query(database, 'Who sent "Transfer request"?')['relationships'][0]['from_label'] == 'Maya Chen'
        assert query(database, 'Which records reference TX-104?')['relationships'][0]['from_label'] == 'Reversal · USD 8000.00'
        assert query(database, 'Who sent an unlisted email?')['status'] == 'unresolved'
        assert query(database, 'Why was the transfer authorized?')['status'] == 'unsupported_question'
        with pytest.raises(duckdb.Error, match='read-only'):
            database.execute('DROP TABLE graph_nodes')
    excerpt = appendix(root, receipt)
    assert 'Contrary citation' in excerpt and 'ledger.txt' in excerpt
    assert 'Withheld draft' not in excerpt and 'Privileged basis' not in excerpt


def test_query_refuses_a_changed_graph_file(archive):
    from domain.case_graph_query import open_graph

    root, _, receipt = archive
    with (root / receipt['path']).open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='integrity'):
        open_graph(root)


def test_saved_graph_keeps_records_beyond_the_visualization_limit(archive):
    from domain.case_graph_query import query
    from domain.case_ontology import PATH, connect, publish
    from domain.workspace_case_map import case_map

    root, workspace, _ = archive
    first = workspace['temporal']['events'][0]
    for i in range(61):
        source_id = f'request-{i}'
        witness = {**first['evidence_refs'][0], 'evidence_id': source_id + '-span', 'source_id': source_id}
        workspace['sources'].append({'source_id': source_id, 'relative_path': source_id + '.eml'})
        workspace['evidence'].append(witness)
        workspace['temporal']['events'].append({**first, 'id': f'email-{i}', 'title': f'Update {i}',
                                                'source_ids': [source_id], 'evidence_refs': [witness]})
    assert case_map(workspace)['omitted_communications'] == 2
    publish(root, workspace)
    with connect(root / PATH, read_only=True) as database:
        receipt = query(database, 'Who sent Update 60?')
        assert receipt['relationships'][0]['from_label'] == 'Maya Chen'
