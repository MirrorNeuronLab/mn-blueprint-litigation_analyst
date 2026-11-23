"""Exercise the communication path contract at collection and decision time."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def blueprint(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "payloads"))
    return root


@pytest.fixture
def graph(tmp_path):
    from domain.models import CaseDocument
    from domain.temporal_evidence import walk

    documents = []
    for n, (sender, recipient, date) in enumerate([
        ("a", "b", "Mon, 03 Mar 2025 12:00:00 +0000"),
        ("b", "c", "Tue, 04 Mar 2025 12:00:00 +0000"),
        ("b", "d", ""), ("b", "e", "Sun, 02 Mar 2025 12:00:00 +0000"),
    ]):
        text = (f"From: {sender}@example.test\nTo: {recipient}@example.test\n"
                + (f"Date: {date}\n" if date else "") + f"Message-ID: <{n}@example.test>\n\nNotice.")
        documents.append(CaseDocument(f"case:m{n}", f"m{n}.eml", "message/rfc822",
            hashlib.sha256(text.encode()).hexdigest(), len(text), text, "case"))
    (tmp_path / "source_inventory.json").write_text(json.dumps({"repository_id": "notice"}))
    corpus = SimpleNamespace(scan=lambda: documents, access_scope="case")
    return walk(tmp_path, corpus, [{"source_id": documents[0].source_id}], "temporal_communication_paths", {})


def test_fresh_and_saved_temporal_paths_reach_the_assessor_with_exact_citations(blueprint, graph):
    from domain.assessment_citations import encode
    from domain.round_tasks import admit_decision, assessment_schema

    assert len(graph["paths"]) == 2 and len(graph["partial_paths"]) == len(graph["rejected_paths"]) == 1
    for path, group in zip(graph["paths"] + graph["partial_paths"], graph["support_groups"], strict=True):
        ids = list(dict.fromkeys(ref["evidence_id"] for edge in path["edges"] for ref in edge["evidence_refs"]))
        assert ids == group["source_evidence_ids"] == path["source_evidence_ids"]
    saved = deepcopy(graph)
    for path in saved["paths"] + saved["partial_paths"]:
        del path["source_evidence_ids"]

    frozen = {"config": json.loads((blueprint / "config/default.json").read_text()), "payload": {"goal": "Trace notice."}}
    task = {"prefix": "r02-H10", "hypothesis": {"id": "H10"}}
    base = {"enquiry": task["hypothesis"], "finding_id": task["prefix"]}
    packets = []
    for result in (graph, saved):
        packet, schema = admit_decision(frozen, "assess", "Test the order of the messages.", base, result["passages"],
            [{"purpose": "graph", "result": result}], {"events": [], "transactions": []},
            lambda spans: assessment_schema(task, {p["evidence_id"] for p in spans}))
        wire, _, ledger = encode(packet, schema)
        exhibits = [p for g in wire["graph_paths"] for p in g["paths"]]
        assert {p["target"] for p in exhibits} == {"b@example.test", "c@example.test"}
        for path in exhibits:
            ids = [ledger[key] for key in path["source_evidence_ids"]]
            assert ids == [ref["evidence_id"] for edge in path["edges"] for ref in edge["evidence_refs"]]
        packets.append(packet)
    assert packets[0] == packets[1]
    assert "source_evidence_ids" not in saved["paths"][0]


@pytest.mark.parametrize("defect", ["empty_edge", "wrong_text", "unknown_id", "wrong_binding", "missing_edge", "wrong_type"])
def test_one_bad_path_preserves_other_verified_paths_and_reports_coverage(graph, defect):
    from domain.evidence_admission import admit
    from domain.review_packets import packet_coverage

    good, bad = sorted(graph["paths"], key=lambda p: len(p["edges"]))
    if defect == "empty_edge":
        bad["edges"][-1]["evidence_refs"] = []
    elif defect == "wrong_text":
        edge = bad["edges"][-1]
        edge["evidence_refs"] = [{**edge["evidence_refs"][0], "text": "unverified exhibit"}]
    elif defect == "unknown_id":
        edge = bad["edges"][-1]
        edge["evidence_refs"] = [{**edge["evidence_refs"][0], "evidence_id": "unavailable"}]
    elif defect == "wrong_binding":
        bad["source_evidence_ids"] = good["source_evidence_ids"]
    elif defect == "missing_edge":
        del bad["edges"]
    else:
        graph["paths"] = [good, None]
    packet = admit(graph["passages"], [{"result": graph}], 100000)
    assert [p for g in packet["graph_paths"] for p in g["paths"]] == [good]
    assert packet["support_admission"]["status"] == "incomplete"
    assert packet["support_admission"]["unavailable_graph_paths"] == 1
    assert packet_coverage(packet["evidence"], [], packet["support_admission"])["unverified_support"] == {
        "unavailable_graph_paths": 1}
    assert "unverified exhibit" not in json.dumps(packet)


@pytest.mark.parametrize("malformed", [None, {}, {"source_evidence_ids": "a"}, {"source_evidence_ids": ["a", {}]}])
def test_malformed_group_withholds_its_connected_dependencies_only(malformed):
    from domain.evidence_admission import IncompleteSupport, admit, review_closure

    a, b, c = spans = [{"evidence_id": i} for i in "abc"]
    records = [{"result": {"passages": [a], "support_groups": [malformed]}},
               {"result": {"passages": [a, b], "support_groups": [{"source_evidence_ids": ["a", "b"], "complete": True}]}},
               {"result": {"passages": [c], "support_groups": [{"source_evidence_ids": [], "complete": False}]}}]
    packet = admit(spans, records, 4096)
    assert packet["evidence"] == [c]
    assert packet["support_admission"]["unresolved_groups"] == 3
    with pytest.raises(IncompleteSupport, match="unresolved dependency"):
        review_closure(spans, records, ["b"])
    assert review_closure(spans, records, ["c"]) == [c]


def test_incomplete_independent_support_withholds_one_finding_and_finishes_the_round(blueprint, tmp_path, monkeypatch):
    from domain import round_tasks
    from domain.evidence.store import EvidenceStore
    from domain.intake import PreparedCorpus
    from domain.models import CaseDocument
    from domain.review_packets import register
    from domain.round_state import load, save

    case = tmp_path / "case"
    case.mkdir()
    text = "Dispatch recorded."
    digest = hashlib.sha256(text.encode()).hexdigest()
    doc = CaseDocument("case:notice", "notice.txt", "text/plain", digest, len(text), text, "case")
    sources = json.dumps([asdict(doc)]).encode()
    (case / "sources.json").write_bytes(sources)
    (case / "source_inventory.json").write_text(json.dumps({"source_root": str(case),
        "sources_sha256": hashlib.sha256(sources).hexdigest()}))
    corpus = PreparedCorpus(case, "case")
    store = EvidenceStore(case / "evidence.sqlite3")
    store.add_sources([doc])
    investigation = store.create_investigation("Trace notice.", "case", llm_model="fixture", graph_path=case / "evidence.rgx")
    eid = hashlib.sha256(f"{doc.source_id}|{digest}|0|{len(text)}".encode()).hexdigest()[:32]
    passage = {"evidence_id": eid, "source_id": doc.source_id, "content_sha256": digest,
               "start_offset": 0, "end_offset": len(text), "text": text}
    record = {"purpose": "support", "action": {"query": "dispatch"}, "result": {"passages": [passage], "status": "matched"}}
    register(store, investigation, [doc], [record])
    task = {"prefix": "r01-H01", "hypothesis": {"id": "H01", "question": "Was notice dispatched?"}}
    frozen = {"config": json.loads((blueprint / "config/default.json").read_text()), "investigation_id": investigation,
              "payload": {"goal": "Trace notice."}, "source_review_flags": {}, "memory_scope": {"job_id": "J", "run_id": "R"}}
    frozen["config"]["text_memory"]["enabled"] = False
    monkeypatch.setattr(round_tasks, "task_input", lambda context, work: (tmp_path, frozen, work))
    monkeypatch.setattr(round_tasks, "validate_indexes", lambda *_: (corpus, {}))
    monkeypatch.setattr(round_tasks, "complete", lambda *_: pytest.fail("An incomplete cited dependency reached the reviewer"))
    prefix = "case/rounds/" + task["prefix"]
    save(tmp_path, prefix + "-evidence.json", {"records": [record], "evidence_ids": [eid]})
    finding = {"id": task["prefix"], "section": "findings", "title": "Dispatch",
               "assessment": text, "evidence_ids": [eid], "limitations": "Receipt is open."}
    save(tmp_path, prefix + "-assessment.json", {
        "hypothesis": {**task["hypothesis"], "status": "supported", "assessment": text,
                       "supporting_evidence": [eid], "contradictory_evidence": [], "outstanding_enquiries": []},
        "report": {"findings": [finding], "conclusion_ids": [task["prefix"]], "follow_up": []},
        "work_items": [], "counsel_issue_ids": []})
    save(tmp_path, prefix + "-review-search.json", {"purpose": "independent_counter", "action": {"query": "return"},
        "result": {"passages": [passage], "status": "incomplete",
                   "support_groups": [{"source_evidence_ids": [eid], "complete": False}]}})

    ctx = SimpleNamespace(resources={})
    result = round_tasks.review_finding(ctx, task)
    review = load(tmp_path, result["review"])
    assert not review["model_dispatched"] and review["accepted_ids"] == []
    assert review["issues"] == ["Cited source has unresolved dependency support"]
    assert review["feedback"]["route"] == "recheck_finding"
    assert round_tasks.review_finding(ctx, task) == result
    summary = round_tasks.summarize_round(ctx, {"revision": 1})
    assert load(tmp_path, summary["summary"])["review"]["accepted_ids"] == []
