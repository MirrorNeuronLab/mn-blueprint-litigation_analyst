import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def payload(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "payloads"))


def test_search_publication_retry_reuse_and_integrity(tmp_path, monkeypatch):
    from domain import search_memory
    from mn_sdk_common.committed_artifacts import CommittedArtifactIntegrityError

    scope = {"job_id": "matter-job", "run_id": "first-review"}
    frozen = {"config": {}, "memory_scope": scope, "indexed": {"sha256": "a" * 64},
              "indexes": {"hashes": {"sources.json": "b" * 64}}}
    session = Mock(scope=scope)
    monkeypatch.setattr(search_memory, "runtime_text_memory", lambda *a, **kw: session)
    args = {"query": "receipt of notice", "top_k": 3}
    result = {"status": "not_found_in_searched_scope", "passages": [], "exhaustive": False,
              "support_groups": [], "unresolved": ["An attachment was unavailable."]}
    search = Mock(return_value=result)
    session.record.side_effect = TimeoutError("publication reply lost")
    with pytest.raises(TimeoutError):
        search_memory.collect(tmp_path, frozen, args, search)
    record = session.record.call_args.args[0]
    kwargs = session.record.call_args.kwargs
    assert kwargs["allow"] == ["round-specialists"]
    assert record.fields["search_status"] == result["status"]
    receipt = {"source_id": "run:" + record.record_id, "revision": "pinned"}
    session.record.side_effect = None
    session.record.return_value = receipt
    recovered = search_memory.collect(tmp_path, frozen, args, search)
    assert recovered == {**result, "reused": True, "search_memory": receipt}
    assert session.record.call_args.args[0] == record
    current = {"source_is_current": True, "dependency_status": "valid", "revision": "pinned",
               "metadata": {"upstream": kwargs["upstream"]}}
    session.client.read_complete.return_value = current
    reused = search_memory.collect(tmp_path, frozen, args, search)
    assert reused == {**result, "reused": True, "search_memory": receipt}
    session.client.read_complete.assert_called_once_with(receipt["source_id"], revision="pinned")
    current["dependency_status"] = "dependency_unavailable"
    with pytest.raises(ValueError, match="no longer current"):
        search_memory.collect(tmp_path, frozen, args, search)
    current["dependency_status"] = "valid"
    (tmp_path / kwargs["upstream"][0]["search_result"]["path"]).write_text("{}")
    with pytest.raises(CommittedArtifactIntegrityError):
        search_memory.collect(tmp_path, frozen, args, search)
    search.assert_called_once()
    assert session.close.call_count == 5

    # Another sealed index cannot locate this search, even under the same Job.
    frozen["indexed"] = {"sha256": "c" * 64}
    session.record.side_effect = lambda r, **kw: {"source_id": "run:" + r.record_id, "revision": "next"}
    assert search_memory.collect(tmp_path, frozen, args, search) == result
    assert session.record.call_args.args[0].record_id != record.record_id
    assert search.call_count == 2


def test_memory_off_runs_each_collector_search(tmp_path):
    from domain.search_memory import collect

    frozen = {"config": {"text_memory": {"enabled": False}}, "memory_scope": {"job_id": "J", "run_id": "R"}}
    search = Mock(side_effect=[{"result": "first"}, {"result": "second"}])
    args = {"query": "dispatch", "top_k": 3}
    assert collect(tmp_path, frozen, args, search) == {"result": "first"}
    assert collect(tmp_path, frozen, args, search) == {"result": "second"}
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(("status", "record", "contrary", "accepted", "route"), [
    ("supported", "", [], True, "ready_for_counsel"),
    ("inconclusive", "", [], True, "trace_gap"),
    ("supported", "", [], False, "recheck_finding"),
    ("contradicted", "", ["P2"], True, "compare_accounts"),
    ("inconclusive", "dispatch.eml", [], True, "reread_record"),
    ("inconclusive", "Witness interview transcript", [], True, "trace_gap"),
    ("inconclusive", "Interview the absent carrier", [], True, "counsel_follow_up"),
    ("inconclusive", "Attorney-client notes", [], False, "handling_review"),
])
def test_review_routes_from_actual_disposition(status, record, contrary, accepted, route):
    from domain.enquiry_review import feedback
    task = {"prefix": "r01-H01"}
    assessment = {"hypothesis": {"id": "H01", "status": status, "contradictory_evidence": contrary,
                                 "outstanding_enquiries": []}, "counsel_issue_ids": ["notice"],
                  "report": {"findings": [{"id": "r01-H01"}]},
                  "work_items": [{"question": "Who received notice?", "requested_record": record,
                                  "closure_condition": "Locate the acknowledgment."}] if record else []}
    review = {"accepted_ids": ["r01-H01"] if accepted else [], "issues": [] if accepted else ["Check the addressee."]}
    independent = {"action": {"query": "receipt"}, "result": {"passages": []}, "purpose": "independent_counter"}
    documents = [SimpleNamespace(source_id="dispatch", relative_path="mail/dispatch.eml", text="Dispatch record")]
    value = feedback(task, assessment, review, {"records": []}, independent, documents)
    assert value["route"] == route
    assert value["withheld_ids"] == ([] if accepted else ["r01-H01"])
    assert value["searches"] == [{"purpose": "independent_counter", "query": "receipt", "passages": 0, "reused": False}]
    if record and route == "trace_gap":
        task["review_direction"] = {"next_records": value["next_records"]}
        second = feedback(task, assessment, review, {"records": []}, independent, documents)
        assert second["route"] == "counsel_follow_up"


def test_follow_up_rereads_only_complete_pinned_counter_search_groups(tmp_path):
    from domain.enquiry_review import follow_up_leads
    from domain.round_state import save

    path = "case/rounds/r01-H01-review-search.json"
    spans = [{"evidence_id": key, "source_id": key, "content_sha256": "a" * 64,
              "start_offset": 0, "end_offset": 12} for key in "ABCDE"]
    groups = [{"complete": complete, "source_evidence_ids": list(ids)} for complete, ids in
              [(True, "AB"), (True, "BC"), (True, "D"), (False, "DE")]]
    ref = save(tmp_path, path, {"result": {"passages": spans, "support_groups": groups}})
    item = {"enquiry_version": "r01-H01", "counter_search_ref": ref}
    leads = follow_up_leads(tmp_path, item)
    assert [[p["source_id"] for p in group] for group in leads] == [["A", "B", "C"]]
    assert all("text" not in p for p in leads[0])
    with pytest.raises(ValueError, match="another enquiry"):
        follow_up_leads(tmp_path, {**item, "enquiry_version": "r01-H02"})
    (tmp_path / path).write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        follow_up_leads(tmp_path, item)


def test_mixed_round_filters_only_completed_or_repeated_enquiries():
    from domain.round_planning import distinct_work
    previous = {"id": "H01", "question": "Who sent the notice?", "support_query": "dispatch",
                "counter_query": "failed notice", "graph_tools": ["a", "b"], "counsel_issue_ids": ["notice"]}
    repeated = {**previous, "support_query": "  Dispatch ", "graph_tools": ["b", "a"]}
    fresh = {**previous, "id": "H02", "counter_query": "return receipt"}
    closed = {**fresh, "id": "H03", "question": "A new wording for a closed enquiry?"}
    assert distinct_work([repeated, closed, fresh], [{"hypotheses": [previous]}], {"H03"}) == [fresh]


@pytest.mark.parametrize("unexamined", [False, True])
def test_adaptive_planner_hands_off_after_addressing_counsel_issues(tmp_path, monkeypatch, unexamined):
    from domain import round_planning
    from domain.matter_intake import empty

    config = json.loads((Path(__file__).resolve().parents[1] / "config/default.json").read_text())
    matter = empty()
    matter["issues"] = [{"id": "notice", "question": "Was notice received?"}]
    if unexamined:
        matter["issues"].append({"id": "timing", "question": "When was notice received?"})
    frozen = {"config": config, "deadline": float("inf"), "matter": matter, "payload": {"goal": "Review the notice."}}
    monkeypatch.setattr(round_planning, "open_round", lambda *_: (tmp_path, frozen))
    monkeypatch.setattr(round_planning, "finish", lambda *_: {})
    monkeypatch.setattr(round_planning, "discover", lambda *a, **kw: {"authorized_readable_sources": 2, "samples": []})
    planner = Mock(return_value={"decision": "stop", "rationale": "Cleared sources did not resolve timing.", "hypotheses": []})
    monkeypatch.setattr(round_planning, "complete", planner)
    feedback = {"id": "H01", "enquiry_version": "r01-H01", "route": "ready_for_counsel",
                "counsel_issue_ids": ["notice"], "next_records": [], "review_issues": [], "searches": []}
    round_planning.save(tmp_path, "case/rounds/summary-01.json", {"findings": [{"id": "H01", "feedback": feedback}]})
    result = round_planning.plan_round(SimpleNamespace(resources={}),
            {"seed": {"context": {"path": "case/rounds/context.json"}}, "_child": {"revision": 1}})
    assert result["done"]
    if unexamined:
        planner.assert_called_once()
        request = planner.call_args.args[5]
        assert request["unexamined_counsel_issue_ids"] == ["timing"]
        assert request["review_queue"][0]["route"] == "ready_for_counsel"
    else:
        planner.assert_not_called()
        assert result["rationale"] == "ready_for_counsel_review"


def test_supplement_prioritizes_only_new_content_inside_the_same_scope(tmp_path):
    from domain.casework import fresh
    from domain.planning_context import supplemental_sources

    case = tmp_path / "case"
    case.mkdir()
    (case / "source_inventory.json").write_text(json.dumps({"repository_id": "notice"}))
    old = {"source_id": "case:notice", "content_sha256": "a" * 64}
    book = fresh({"matter_id": "notice", "access_scope": "legal", "snapshot_id": "first", "sources": [old]})
    export = {"version": "mn.litigation.review.v1", "matter_id": "notice", "casework": book}
    packet = case / "review-input.json"
    packet.write_text(json.dumps(export))
    frozen = {"payload": {"review_file": str(packet)}, "config": {"investigation": {"access_scope": "legal"}}}
    docs = [SimpleNamespace(**row) for row in (old, {**old, "source_id": "case:copy"},
            {"source_id": "case:deposition", "content_sha256": "b" * 64})]
    assert supplemental_sources(tmp_path, frozen, docs) == {"case:deposition"}
    assert supplemental_sources(tmp_path, frozen, docs[1:]) == set()
    book["scope"] = "other"
    packet.write_text(json.dumps(export))
    with pytest.raises(ValueError, match="different matter or access scope"):
        supplemental_sources(tmp_path, frozen, docs)
