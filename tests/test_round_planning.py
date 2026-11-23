import json
from pathlib import Path
import time
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    "corrected_query",
    ["routine duties", "approval  NOTICE"],
    ids=["corrected", "still-duplicate"],
)
def test_planner_corrects_duplicate_searches_before_scheduling(tmp_path, monkeypatch, corrected_query):
    blueprint = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(blueprint / "payloads"))
    from domain import round_planning

    config = json.loads((blueprint / "config/default.json").read_text())
    config["text_memory"]["enabled"] = False
    frozen = {
        "config": config,
        "deadline": time.time() + 60,
        "payload": config["inputs"]["payload"],
    }
    overview = {
        "authorized_readable_sources": 1,
        "samples": [{"passages": [{"source_id": "case:notice", "content_sha256": "a" * 64,
                                   "start_offset": 0, "end_offset": 57,
                                   "text": "Approval notice. Routine duties explain the correspondence."}]}],
    }
    monkeypatch.setattr(round_planning, "open_round", lambda *_: (tmp_path, frozen))
    monkeypatch.setattr(round_planning, "discover", lambda *_: overview)
    queries = iter([" APPROVAL NOTICE ", corrected_query])
    requests = []

    class Model:
        def completion_text(self, system, user):
            requests.append((system, json.loads(user)))
            return json.dumps({
                "decision": "execute",
                "rationale": "Review the notice and ordinary explanations.",
                "hypotheses": [{
                    "id": "H01",
                    "question": "Does the notice establish approval?",
                    "support_query": "approval notice",
                    "counter_query": next(queries),
                    "expected_information": "Distinguish approval from routine correspondence.",
                    "counsel_issue_ids": [],
                    "graph_tools": [],
                }],
            })

    context = SimpleNamespace(resources={"llm": Model()})
    work = {"seed": {"context": {"path": "case/rounds/context.json"}}, "_child": {"revision": 0}}
    rounds = tmp_path / "case/rounds"
    if corrected_query == "routine duties":
        plan = round_planning.plan_round(context, work)
        assert plan["tasks"][0]["template"] == "collect_litigation_evidence"
        task = json.loads((rounds / "tasks/r01-H01.json").read_text())
        assert task["hypothesis"]["counter_query"] == corrected_query
        assert round_planning.plan_round(context, work) == plan
        assert (rounds / "models/plan-00-search-correction.json").is_file()
    else:
        with pytest.raises(ValueError, match="distinct support and counter-evidence searches"):
            round_planning.plan_round(context, work)
        assert not (rounds / "proposal-00.json").exists()
        assert not (rounds / "tasks").exists()
        assert not list((rounds / "models").glob("*.json"))

    assert len(requests) == 2
    assert requests[0][1]["source_overview"] == requests[1][1]["source_overview"] == overview
    assert "ordinary explanation" in requests[1][0]
    assert not (rounds / "models/plan-00.json").exists()
