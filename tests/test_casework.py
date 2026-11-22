"""Exercise the notice pilot through publication, trusted carryover and the offline index."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'payloads'))


def publish_pilot(root, second=False, review_file=None):
    from domain.case_ontology import PATH, connect, publish
    from domain.casework_index import offline_index
    from domain.ingestion.corpus import CaseCorpus
    from domain.matter_intake import prepare
    from domain.privilege_log import publish as publish_log
    from domain.workspace_graph import attach
    from domain.workspace_history import publish as history
    from domain.workspace_projection import build
    from domain.workspace_web import publish as web

    sample = ROOT / 'examples/notice_review'
    root = Path(root)
    context = SimpleNamespace(store=SimpleNamespace(run_dir=root), job_data_dir=root.parent/'job',
                              job_id='notice-pilot', run_id=root.name,
                              config=json.loads((ROOT/'config/default.json').read_text()))
    context.config['workspace'] = {'matter_name':'Synthetic notice review'}
    matter = prepare(context, {'matter_file': str(sample/'matter.json')})
    docs = CaseCorpus(sample/'first-production', 'case').scan()
    if second:
        docs += CaseCorpus(sample/'supplement', 'case').scan()
    original_dir = root/'case/originals'
    original_dir.mkdir(exist_ok=True)
    files = []
    for d in docs:
        path = sample/'first-production'/d.relative_path
        if not path.exists():
            path = sample/'supplement'/d.relative_path
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        (original_dir/digest).write_bytes(data)
        files.append({'path':d.relative_path, 'sha256':digest})
    inventory = {'repository_id':'notice-pilot', 'files':files, 'sample':True}
    ws = build(context, docs, [], {'data':{},'stop_reason':'completed'}, inventory, goal=matter['intended_decision'])
    attach(ws, root/'case', {})
    history(context, ws, review_file=review_file)
    publish(root, ws)
    with connect(root/PATH,read_only=True) as db:
        ws['case_query_index'] = offline_index(db,ws)
    publish_log(root,matter['privilege_log'])
    status, _ = web(context,ws)
    assert status['status']=='Available', status
    return ws


def make_book(ws):
    b = deepcopy(ws['casework'])
    element = b['elements'][1]['id']
    for key,role,quote,sid in [
        ('denial','Contrary','I did not receive the notice for shipment A before termination.','case:deposition.txt'),
        ('other','Context','Jordan Lee signed for shipment B and acknowledged receipt of its notice.','case:shipment-b.txt')]:
        src=next(s for s in ws['sources'] if s['source_id']==sid)
        start=src['text'].index(quote)
        b['facts'].append({'id':key,'element':element,'wording':quote,'role':role,'actor':'Pilot counsel',
                           'witness':'Jordan Lee','approved':True,'reviewed_snapshot':ws['snapshot_id'],
                           'anchor':{'source':sid,'hash':src['content_sha256'],'start':start,'end':start+len(quote),
                                     'quote':quote,'pin':''}})
    b['outlines']=[{'id':'depo','element':element,'witness':'Jordan Lee','statement':'denial','exhibit':'other',
                    'question':'Which shipment did you sign for?', 'resolution':'The signed exhibit identifies shipment B.'}]
    b['queries']=[{'id':'q1','chain':['Which records address receipt?', 'Which of those predate termination?']}]
    return b


def packet(ws, book, location):
    location.write_text(json.dumps({'version':'mn.litigation.review.v1','matter_id':ws['matter_id'],
                                   'snapshot_id':ws['snapshot_id'],'casework':book,'decisions':[]}))
    return location


def test_two_productions_persist_authorized_graph_and_work(tmp_path):
    from domain.case_ontology import PATH, connect
    from domain.case_graph_query import query
    first = publish_pilot(tmp_path/'first')
    second = publish_pilot(tmp_path/'second',True,packet(first,make_book(first),tmp_path/'review.json'))
    assert second['casework_changed_sources']==['case:acknowledgment.txt']
    assert second['casework']['outlines'][0]['resolution'].endswith('shipment B.')
    assert second['casework']['queries'][0]['chain'][1]=='Which of those predate termination?'
    assert len(second['casework']['elements'])==2
    with connect(tmp_path/'second'/PATH,read_only=True) as db:
        assert db.execute('select count(*) from proof_elements').fetchone()==(2,)
        assert db.execute('select count(*) from reviewed_facts').fetchone()==(2,)
        assert db.execute("select count(*) from graph_edges where relation='CONTESTED_BY_FACT'").fetchone()==(1,)
        result = query(db, 'Which facts contradict the element Customer received notice for shipment A?')
        assert result['status']=='matched'
        assert result['relationships'][0]['passages'][0]['document']=='deposition.txt'
    assert any(d['meaning']=='Termination' and d['earliest']=='2024-05-10' for d in second['case_query_index']['dates'])
    assert any(d['wording']=='early April 2024' and d['earliest']!=d['latest'] for d in second['case_query_index']['dates'])
    assert 'PRIV-001' not in (tmp_path/'second/web/index.html').read_text()
    assert 'PRIV-001' in (tmp_path/'second/case/privilege_log.html').read_text()


def test_restore_fails_closed_and_stale_clips_lose_approval(tmp_path):
    from domain.casework import prepare
    ws=publish_pilot(tmp_path/'first')
    b=make_book(ws)
    tampered=deepcopy(b)
    tampered['facts'][0]['anchor']['quote']='x'*len(tampered['facts'][0]['anchor']['quote'])
    with pytest.raises(ValueError,match='differs'):
        prepare(deepcopy(ws),tampered)
    other=deepcopy(b); other['scope']='different scope'
    with pytest.raises(ValueError,match='different matter'):
        prepare(deepcopy(ws),other)
    narrower=deepcopy(ws); narrower['sources']=narrower['sources'][:1]
    assert not prepare(narrower,b)['facts']
    changed=deepcopy(ws)
    doc=next(s for s in changed['sources'] if s['source_id']=='case:deposition.txt')
    doc['text']='Corrected testimony.'
    doc['content_sha256']=hashlib.sha256(doc['text'].encode()).hexdigest()
    old=prepare(changed,b)['facts'][0]
    assert old['binding']=='changed' and old['approved'] is False


def test_verified_pdf_pages_use_parser_boundaries(tmp_path,monkeypatch):
    from domain.ingestion.corpus import CaseCorpus
    import mn_docs_to_markdown_skill
    (tmp_path/'record.pdf').write_bytes(b'fixture')
    monkeypatch.setattr(mn_docs_to_markdown_skill,'extract_pages_from_pdf',lambda _: [
        {'page_number':1,'text':'Exhibit A\nPage 99:\nnot a page boundary.'},
        {'page_number':2,'text':'Signed acknowledgment.'}])
    doc,=CaseCorpus(tmp_path).scan()
    assert [n for n,_,_ in doc.page_spans]==[1,2]
    assert [doc.text[a:z] for _,a,z in doc.page_spans][1]=='Signed acknowledgment.'


def test_private_inputs_never_enter_the_graph_or_prompt(tmp_path):
    from domain.intake import case_corpus
    from domain.matter_intake import empty, prompt_scope
    for name in ('evidence.txt','counsel.json','review.json'):
        (tmp_path/name).write_text('Readable text')
    records=case_corpus(tmp_path,'case',{'matter_file':str(tmp_path/'counsel.json'),
                                        'review_file':str(tmp_path/'review.json')},sample=False).scan()
    assert [r.relative_path for r in records]==['evidence.txt']
    matter=json.loads((ROOT/'examples/notice_review/matter.json').read_text())
    assert 'PRIV-001' not in json.dumps(prompt_scope({**empty(), **matter}))


def test_alias_decisions_require_exact_identity_evidence(tmp_path):
    from domain.casework import prepare
    w=publish_pilot(tmp_path/'first')
    book=make_book(w)
    book['aliases']=[{'id':'a','alias':'Jordan','person':'Unrelated witness','fact':'other',
                      'actor':'Counsel','at':'2024-05-10T01:00:00Z','reverses':''}]
    with pytest.raises(ValueError,match='both names'):
        prepare(deepcopy(w),book)
    book['aliases'][0]['person']='Jordan Lee'
    book['aliases'].append({**book['aliases'][0],'id':'another'})
    with pytest.raises(ValueError,match='active alias'):
        prepare(deepcopy(w),book)
    book['aliases'][1].update(reverses='a')
    assert prepare(deepcopy(w),book)['aliases'][1]['reverses']=='a'


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Publish the synthetic notice pilot through the blueprint report modules.")
    parser.add_argument('run', type=Path)
    parser.add_argument('--review', type=Path, help="Include the supplemental production and this saved review.")
    args = parser.parse_args()
    publish_pilot(args.run, second=bool(args.review), review_file=args.review)

