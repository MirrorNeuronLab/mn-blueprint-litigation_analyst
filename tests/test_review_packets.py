"""Regressions for crowded first-pass decisions and the published review brief."""
import hashlib
import json
from itertools import combinations_with_replacement
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator


@pytest.fixture
def blueprint(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "payloads"))
    return root


@pytest.mark.parametrize("previous_limits", [False, True], ids=["default", "original-16k-window"])
def test_crowded_search_charges_only_admitted_citations(blueprint, previous_limits):
    from domain.round_model import evidence_room
    from domain.round_tasks import admit_decision, assessment_schema

    config = json.loads((blueprint / "config/default.json").read_text())
    if previous_limits:
        config["context_memory"]["policy"].update(window_tokens=16384, output_tokens=2048)
    frozen = {"config": config, "payload": {"goal": "Examine the recorded estimate and revised estimate."}}
    task = {"hypothesis": {"id": "H01"}, "prefix": "r01-H01"}
    records = []
    # Multiple collection copies compete with two independent source accounts.
    for purpose, text in [("support", "The register records an estimate of USD 40."),
                          ("counter", "An amendment revises the estimate to USD 30.")]:
        matches = []
        for n in range(70):
            source_id = f"case:collection/{n}/{purpose}.txt"
            matches.append({"evidence_id": hashlib.sha256(source_id.encode()).hexdigest()[:32],
                "source_id": source_id, "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "start_offset": 0, "end_offset": len(text), "text": text})
        records.append({"purpose": purpose, "result": {"passages": matches, "status": "ranked"}})
    spans = [p for r in records for p in r["result"]["passages"]]
    ids = {p["evidence_id"] for p in spans}
    base = {"enquiry": task["hypothesis"], "finding_id": task["prefix"], "graph_observations": []}
    def schema_for(selected):
        return assessment_schema(task, {p["evidence_id"] for p in selected})
    packet, schema = admit_decision(frozen, "assess", "Compare original accounts.", base, spans, records,
        {"events": [], "transactions": []}, schema_for, collected_ids=ids,
        graph_observations=[{"preview": "x" * 20000}])
    visible = {p["evidence_id"] for p in packet["evidence"]}
    assert 0 < len(visible) < len(ids)
    assert {p["text"] for p in packet["evidence"]} == {r["result"]["passages"][0]["text"] for r in records}
    assert all(row["evidence_ids"] for row in packet["search_coverage"])
    assert {i for row in packet["search_coverage"] for i in row["evidence_ids"]} == visible
    assert set(schema["$defs"]["passage"]["enum"]) == visible
    assert packet["omitted_passages"] == len(ids - visible)
    assert packet["graph_observations"] == []
    assert evidence_room(frozen, "assess", "Compare original accounts.", packet, schema) > 0


def test_default_output_reserve_matches_the_primary_model_request(blueprint):
    config = json.loads((blueprint / "config/default.json").read_text())
    llm = json.loads((blueprint / "extensions/llm.json").read_text())
    policy = config["context_memory"]["policy"]
    assert policy["output_tokens"] == llm["configs"][llm["default_config"]]["max_tokens"] == 8192
    assert policy["window_tokens"] == 65536


def test_oversize_passage_remains_readable_but_cannot_ground_a_finding(blueprint):
    from domain.round_tasks import assessment_schema

    task = {"hypothesis": {"id": "H01"}, "prefix": "r01-H01"}
    schema = assessment_schema(task, {"short", "long"}, {"short"})
    item = schema["properties"]["report"]["properties"]["findings"]["items"]["properties"]["evidence_ids"]
    assert Draft202012Validator(item).is_valid(["short"])
    assert not Draft202012Validator(item).is_valid(["long"])
    assert set(schema["$defs"]["passage"]["enum"]) == {"short", "long"}
    no_citation = assessment_schema(task, {"long"}, set())
    assert no_citation["properties"]["report"]["properties"]["findings"]["maxItems"] == 0


def test_short_citations_round_trip_without_rewriting_source_text(blueprint):
    from domain.assessment_citations import encode, decode
    from domain.round_tasks import assessment_schema

    ids = ["1" * 32, "2" * 32]
    passages = [{"evidence_id": eid, "source_id": "case:letter.txt", "content_sha256": "a" * 64,
                 "start_offset": n, "end_offset": n + 2, "text": "E2"} for n, eid in enumerate(ids)]
    packet = {"evidence": passages, "search_coverage": [{"purpose": "support", "evidence_ids": ids}],
        "verified_financial": {"events": [{"evidence_ids": ids[:1]}], "transactions": []},
        "graph_paths": [{"paths": [{"source_evidence_ids": ids}]}]}
    schema = assessment_schema({"hypothesis": {"id": "H01"}, "prefix": "r01-H01"}, set(ids), {ids[0]})
    wire, grammar, ledger_ids = encode(packet, schema)
    assert [p["ledger_id"] for p in wire["evidence"]] == ids
    assert all(p["text"] == "E2" for p in wire["evidence"])
    assert wire["normalized_source_hashes"]["case:letter.txt"] == "a" * 64
    assert wire["graph_paths"][0]["paths"][0]["source_evidence_ids"] == ["E1", "E2"]
    assert wire["verified_financial"]["events"][0]["evidence_ids"] == ["E1"]
    assert grammar["$defs"]["passage"]["enum"] == ["E1", "E2"]
    assert grammar["properties"]["report"]["properties"]["findings"]["items"]["properties"]["evidence_ids"]["items"]["enum"] == ["E1"]
    response = {"hypothesis": {"supporting_evidence": ["E1"], "contradictory_evidence": ["E2"]},
        "report": {"findings": [{"title": "E2", "evidence_ids": ["E1"]}]}, "work_items": [{"evidence_ids": ["E2"]}]}
    saved = decode(response, ledger_ids)
    assert saved["hypothesis"]["supporting_evidence"] == ids[:1]
    assert saved["hypothesis"]["contradictory_evidence"] == ids[1:]
    assert saved["report"]["findings"][0] == {"title": "E2", "evidence_ids": ids[:1]}
    assert saved["work_items"][0]["evidence_ids"] == ids[1:]
    assert packet["evidence"][0]["evidence_id"] == ids[0]


def test_finding_grammar_enforces_the_combined_byte_limit_before_dispatch(blueprint):
    from domain.assessment_citations import finding_citations

    # The live assessor cited duplicate copies of a 501-byte memo passage and
    # a 1,152-byte message, in addition to an 89-byte passage.
    sizes = dict(zip(("E1", "E3", "E5", "E7", "E8", "E2"), (501, 501, 501, 1152, 1152, 89)))
    validator = Draft202012Validator(finding_citations(sizes))
    assert not validator.is_valid(["E1", "E3", "E5", "E7", "E8", "E1", "E2"])
    for count in range(1, len(sizes) + 1):
        for choice in combinations_with_replacement(sizes, count):
            actual = sum(sizes[k] for k in set(choice))
            valid = validator.is_valid(list(choice))
            assert not valid or actual <= 2000
            if count <= 2 and len(set(choice)) == count and actual <= 2000:
                assert valid
    boundary = Draft202012Validator(finding_citations({"A": 1200, "B": 800, "C": 801}))
    assert boundary.is_valid(["A", "B"]) and not boundary.is_valid(["A", "C"])
    mixed = Draft202012Validator(finding_citations(dict(zip("ABCDE", (501, 280, 516, 900, 950)))))
    assert mixed.is_valid(["A", "B", "C"])
    assert not mixed.is_valid(["A", "D", "E"])


def test_planner_lead_missed_by_ranked_search_is_reread_with_its_qualification(blueprint):
    from domain.planning_context import source_leads
    from domain.review_packets import reread_leads

    text = "A memo reports a USD 24.5 million trace.\nBank confirmation is pending."
    digest = hashlib.sha256(text.encode()).hexdigest()
    doc = SimpleNamespace(source_id="case:memo", content_sha256=digest, text=text)
    cut = text.index("\n") + 1
    spans = [{"source_id": doc.source_id, "content_sha256": digest, "start_offset": a, "end_offset": b,
              "text": text[a:b]} for a, b in [(0, cut), (cut, len(text))]]
    hypothesis = {"question": "What does the reported trace establish?", "support_query": "24.5 million",
                  "counter_query": "bank confirmation"}
    leads = source_leads({"samples": [{"passages": spans}]}, hypothesis)
    assert len(leads) == 1 and all("text" not in ref for ref in leads[0])
    result = reread_leads(leads, [doc], {}, [])["result"]
    assert [p["text"] for p in result["passages"]] == [text[:cut], text[cut:]]
    assert result["support_groups"][0]["source_evidence_ids"] == [p["evidence_id"] for p in result["passages"]]
    assert not reread_leads(leads, [doc], {doc.source_id: "restricted"}, [])["result"]["passages"]
    leads[0][0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="frozen source"):
        reread_leads(leads, [doc], {}, [])


def test_brief_presents_only_retained_findings_without_counsel_intake(blueprint):
    from domain.review_products import issue_brief

    finding = {"id": "F1", "title": "Revised estimate", "review_state": "AI draft",
               "assessment": "The amendment records an estimate of USD 30.",
               "limitations": "Actual expenditure remains unresolved.",
               "evidence_ids": ["a"], "supporting_evidence": ["a"], "counter_evidence": []}
    workspace = {"findings": [finding, {**finding, "id": "F2", "title": "Dismissed wording", "review_state": "Dismissed"}],
        "evidence": [{"evidence_id": "a"}], "issues": [], "gaps": [], "counsel_issues": [],
        "matter_scope": {"intended_decision": ""}, "goal": "Review recorded costs.",
        "financial_review": {"evidence": [], "events": [], "transactions": []},
        "coverage": {"readable_ids": ["doc"], "source_ids": ["doc"]},
        "analysis": {"review_plan": {"profile": "first_pass", "max_rounds": 1, "max_decisions": 6,
            "relationship_call_ceiling": 0, "seconds": 600, "definition": "Ranked review."}}}
    brief = issue_brief(workspace)
    assert brief.index("Revised estimate") < brief.index("Your next review")
    assert finding["assessment"] in brief and finding["limitations"] in brief
    assert "evidence_appendix.md#evidence-a" in brief
    assert "Dismissed wording" not in brief
    assert "| Reference |" not in brief and "zero accounting net" not in brief
    assert "## Internal review work" not in brief
    workspace["findings"] = []
    assert "No finding cleared review" in issue_brief(workspace)
