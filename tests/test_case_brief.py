"""A matter can have useful exhibits and open work without an accepted finding."""
from hashlib import sha256
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def payload(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'payloads'))


def test_unresolved_brief_preserves_exact_citations_and_separate_copies():
    from domain.workspace_review import attach

    memo = 'SUBJECT: Shipment notice\n\nThe receipt covers shipment B only.'
    denial = 'I did not sign for shipment A.'
    sources, evidence = [], []
    for sid, text in [('matter/memo.txt', memo), ('copies/memo.txt', memo), ('witness.txt', denial)]:
        digest = sha256(text.encode()).hexdigest()
        sources.append(dict(source_id=sid, relative_path=sid, text=text, content_sha256=digest))
        evidence.append(dict(evidence_id=f'p{len(evidence)}', source_id=sid, text=text,
                             content_sha256=digest, start_offset=0, end_offset=len(text)))
    question = 'Which shipment does the receipt identify?'
    workspace = dict(sources=sources, evidence=evidence, findings=[], goal=question,
                     temporal={'events': [], 'nodes': []}, analysis={'status': 'Draft', 'scope': 'Supplied records'},
                     issues=[dict(question=question, supporting_evidence=['p0', 'p1'], contradictory_evidence=['p2'],
                                  status='inconclusive', assessment='Unreviewed narrative marker')],
                     gaps=[dict(id='gap', question=question, why_it_matters='Unverified corpus-wide claim',
                                requested_record='Signed receipt for shipment A', closure_condition='Identify the shipment on the receipt.',
                                source_evidence_ids=['p0', 'p1'])])

    result = attach(workspace)
    brief = result['case_brief']
    assert brief['cited_ids'] == ['p0', 'p1', 'p2']
    assert brief['highlights'] == [{'evidence_id': 'p0', 'excerpt': 'The receipt covers shipment B only.'},
                                   {'evidence_id': 'p2', 'excerpt': denial}]
    assert brief['titles'] == {'matter/memo.txt': 'Shipment notice', 'copies/memo.txt': 'Shipment notice',
                                'witness.txt': 'witness.txt'}
    report = result['reading_reports'][0]['markdown']
    assert 'No finding cleared review' in report and 'Questions examined' in report
    assert 'Signed receipt for shipment A' in report and 'Contrary passages' in report
    assert all(f'exact-source-passages.md#p{i}' in report for i in range(3))
    assert 'What the transaction records show' not in report
    assert 'Unreviewed narrative marker' not in report and 'Unverified corpus-wide claim' not in report
    assert result['findings'] == []


def test_excerpt_preserves_wrapped_qualifications_and_never_clips_long_passages():
    from domain.case_brief import excerpt

    qualified = 'Payment was proposed\nbut remained subject to approval.'
    assert excerpt('Records:\n- Unrelated item.\n- ' + qualified, 'Was payment approved?') == qualified
    assert excerpt('Payment ' + 'qualifications ' * 25 + '\n\nRegards, Morgan', 'Was payment approved?') == ''
