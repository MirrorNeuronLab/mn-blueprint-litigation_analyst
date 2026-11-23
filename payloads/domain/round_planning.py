"""LLM-directed litigation enquiries compiled into admitted child tasks."""

from mn_sdk.blueprint.hooks import activity_operation
import time
from copy import deepcopy
from .app.planning import object_schema
from .round_state import open_round, read, save, finish
from .round_model import InvalidSearchPair, complete, evidence_room
from .planning_context import discover, source_leads
from .review_scope import limits
from .enquiry_review import COUNSEL_ROUTES, follow_up_leads, planning_item
from .matter_intake import prompt_scope
from .graph_queries import QUERIES
from .source_graph import VIEWS
from .temporal_evidence import VIEWS as TEMPORAL_VIEWS

TEXT = {"type": "string", "minLength": 1, "maxLength": 500}
ENQUIRY = object_schema({
    "id": {"type": "string", "pattern": "^H[0-9]{2}$"},
    "question": TEXT, "support_query": TEXT, "counter_query": TEXT,
    "expected_information": TEXT,
    "counsel_issue_ids": {"type": "array", "maxItems": 20, "uniqueItems": True, "items": {"type": "string"}},
    "graph_tools": {"type": "array", "maxItems": 2, "uniqueItems": True, "items": {"enum": sorted({**QUERIES, **VIEWS, **TEMPORAL_VIEWS})}},
})


def distinct_work(hypotheses, earlier, closed_ids):
    def signature(h):
        terms = tuple(" ".join(h[k].casefold().split()) for k in ("question", "support_query", "counter_query"))
        return terms, tuple(sorted(h["graph_tools"])), tuple(sorted(h["counsel_issue_ids"]))

    seen = {signature(h) for proposal in earlier for h in proposal["hypotheses"]}
    selected = []
    for h in hypotheses:
        key = signature(h)
        if h["id"] not in closed_ids and key not in seen:
            selected.append(h)
            seen.add(key)
    return selected


@activity_operation('Planning the investigation round', completed='Planning the investigation round: completed')
def plan_round(context, work):
    reference = work["seed"]["context"]
    root, frozen = open_round(context, reference)
    llm_client = context.resources.get("llm")
    revision = work["_child"]["revision"]
    name = f"case/rounds/plan-{revision:02d}.json"
    if (root / name).exists():
        saved = read(root / name)
        if saved["context"] != reference:
            raise ValueError("Cached litigation plan belongs to another context")
        return saved["plan"]
    cfg = limits(frozen["config"])
    reason = None
    if (root / "case/cancel.request").exists():
        reason = "cancelled"
    elif time.time() >= frozen["deadline"]:
        reason = "investigation_deadline_reached"
    elif revision >= cfg["max_rounds"]:
        reason = "maximum_rounds_reached"
    previous = []
    queue = []
    prior_reviews = {}
    closed_ids = set()
    issue_ids = [i["id"] for i in frozen.get("matter", {}).get("issues", [])]
    unexamined = set(issue_ids)
    if revision and not reason:
        for finding in read(root / f"case/rounds/summary-{revision:02d}.json")["findings"]:
            previous.append({k: v for k, v in finding.items() if k != "feedback"})
            item = planning_item(finding["feedback"])
            queue.append(item)
            prior_reviews[item["id"]] = finding["feedback"]
            unexamined.difference_update(item["counsel_issue_ids"])
            if cfg["profile"] == "adaptive" and item["route"] in COUNSEL_ROUTES:
                closed_ids.add(item["id"])
        if queue and cfg["profile"] == "adaptive" and len(closed_ids) == len(queue) and not unexamined:
            reason = "ready_for_counsel_review"
    if reason:
        value = {"decision": "stop", "rationale": reason, "hypotheses": []}
    else:
        schema = object_schema({"decision": {"enum": ["execute"] if not revision else ["execute", "stop"]}, "rationale": TEXT,
            "hypotheses": {"type": "array", "minItems": 1 if not revision else 0,
                           "maxItems": cfg["hypotheses_per_round"], "items": deepcopy(ENQUIRY)}})
        field = schema["properties"]["hypotheses"]["items"]["properties"]["counsel_issue_ids"]
        if issue_ids:
            field["items"] = {"enum": issue_ids}
        else:
            field["maxItems"] = 0
        instruction = (
            "The source_overview contains authorized current-case navigation. Use its filenames and complete source examples "
            "to discover names, events and search terms even when counsel_scope and historical runtime_memory are empty. "
            "Empty historical memory is not an empty source corpus. Navigation is not a report finding: collect support "
            "and counterevidence before making factual claims. Execute selects concrete falsifiable enquiries with distinct support and counter searches. "
            "Anchor initial enquiries to specific statements in the samples. For follow-ups use reviewed source leads, "
            "including those outside the initial sample. Use distinctive names, amounts or phrases "
            "in the lexical search. Test a qualification, alternative account or independent record with the other search. "
            "When the goal is broad, choose distinct documented events. Do not assume an unmentioned transaction or allegation. "
            "support_query and counter_query must be short lexical case terms (names, transaction IDs, approval, reversal), "
            "never tool names, graph views, filter instructions or a description of an operation. "
            "Select zero to two named graph_tools from the admitted views only when they reduce uncertainty. Never write RGQL. "
            "Use clause_dependencies for definitions/references, qualification_paths for conditions/exceptions, "
            "amendment_paths for explicit amendments, and clause_statements for cited extraction proposals. "
            "These views bind their seeds to the current support/counter source searches; proposals are not established facts. "
            "Use temporal_communication_paths to test strict chronology of top-level addressing; unknown clocks/identity "
            "and rejected paths remain explicit. Addressing does not prove delivery, knowledge, material transfer or continuous roles. "
            "Use stable Hnn IDs when revising earlier enquiries. Change searches based on prior evidence and unresolved issues. "
            "Tag each enquiry with its supplied counsel_issue_ids, or [] when no counsel issue matches. "
            "Prioritize the supplied counsel questions and intended decision; counsel scope is review direction, not source evidence or verified law. "
            "Track distinct issues; do not silently equate approval, posting, reversal, bank settlement and loss. "
            "On later rounds prioritize unexamined counsel issues and the review_queue. For a withheld finding, "
            "test the reviewer's specific objection. For conflicting accounts, seek an independent source. "
            "For an internal reread, use the requested record and closure condition. Leave handling decisions "
            "and external collection with counsel. Stop when further authorized searches offer no new basis. "
            "When the overview marks a source new_or_revised, test what it changes against an earlier account. "
        )
        plan_instruction = (
            "On revision zero choose execute with at least one enquiry; later choose execute or stop. "
            f"{instruction}Stop requires a concrete reason and an empty hypotheses list. Do not stop before examining evidence. "
        )
        data = {"goal": frozen["payload"]["goal"], "counsel_scope": prompt_scope(frozen.get("matter", {})) if frozen.get("matter") else {},
                "revision": revision, "prior_findings": previous, "remaining_rounds": cfg["max_rounds"] - revision,
                "graph_views": sorted({*QUERIES, *VIEWS, *TEMPORAL_VIEWS})}
        if revision:
            data.update(review_queue=queue, unexamined_counsel_issue_ids=sorted(unexamined))
        room = min(evidence_room(frozen, 'plan', plan_instruction, data, schema),
                   frozen['config'].get('text_memory', {}).get('max_context_bytes', 32768), 16384)
        # Include the field wrapper and final coverage envelope in the allowance.
        capacity = max(0, room - 256)
        if queue:
            focus = [term for item in queue if item["route"] not in COUNSEL_ROUTES
                     for term in [*item["review_concerns"], *(r["requested_record"] for r in item["next_records"])]]
            overview = discover(root, frozen, capacity, follow_up=focus)
        else:
            overview = discover(root, frozen, capacity)
        data['source_overview'] = overview or {}
        if overview is not None and not overview['authorized_readable_sources']:
            value = {"decision": "stop", "rationale": "no_authorized_readable_sources", "hypotheses": []}
        elif not revision and (overview is None or not overview['samples']):
            raise ValueError(
                "Case analysis did not start: no complete authorized source passage fits the planning context. "
                "Increase context_memory.policy.window_tokens or narrow the source scope, then start a new run."
            )
        else:
            key = f"plan-{revision:02d}"
            try:
                value = complete(root, frozen, key, "plan", plan_instruction, data, schema, llm_client)
            except InvalidSearchPair:
                correction = (
                    "Correct the repeated or blank searches. Return an execute plan with distinct, nonempty terms. "
                    "Use counter_query to find a conflicting record or an ordinary explanation. "
                    f"{instruction}"
                )
                correction_schema = deepcopy(schema)
                correction_schema["properties"]["decision"]["enum"] = ["execute"]
                correction_schema["properties"]["hypotheses"]["minItems"] = 1
                value = complete(
                    root, frozen, f"{key}-search-correction", "plan", correction,
                    data, correction_schema, llm_client,
                )
        if value["decision"] == "execute" and not value["hypotheses"]:
            if not revision:
                raise ValueError("Execute requires distinct enquiries")
            value = {"decision": "stop", "rationale": "no_distinct_enquiries_proposed", "hypotheses": []}
        if value["decision"] == "execute":
            if len({h["id"] for h in value["hypotheses"]}) != len(value["hypotheses"]):
                raise ValueError("Execute requires distinct enquiries")
            from .round_tasks import validate_graph_query
            for h in value["hypotheses"]:
                for query in h["graph_tools"]:
                    if query in QUERIES:
                        validate_graph_query(QUERIES[query])
            earlier = [read(p)["proposal"] for p in sorted((root / "case/rounds").glob("proposal-*.json"))]
            value = {**value, "hypotheses": distinct_work(value["hypotheses"], earlier, closed_ids)}
            if not value["hypotheses"]:
                value = {"decision": "stop", "rationale": "no_new_evidence_work_proposed", "hypotheses": []}
        elif value["hypotheses"] or (not revision and value['rationale'] != 'no_authorized_readable_sources'):
            raise ValueError("Planner cannot skip initial evidence collection or execute work while stopping")
    save(root, f"case/rounds/proposal-{revision:02d}.json", {"proposal": value})
    if value["decision"] == "stop":
        output = finish(context, frozen, value["rationale"], reference, revision)
        result = {"done": True, "tasks": [], "rationale": value["rationale"]}
    else:
        output = None
        steps, previous = [], []
        for h in value["hypotheses"]:
            prefix = f"r{revision+1:02d}-{h['id']}"
            leads = source_leads(data["source_overview"], h) if data["source_overview"] else []
            item = next((row for row in queue if row["id"] == h["id"]), None)
            task_data = {"hypothesis": h, "prefix": prefix, "source_leads": leads}
            if item and item["route"] not in COUNSEL_ROUTES:
                task_data["review_direction"] = {k: item[k] for k in ("enquiry_version", "route", "review_concerns", "next_records")}
                leads.extend(group for group in follow_up_leads(root, prior_reviews[h["id"]]) if group not in leads)
            task = save(root, f"case/rounds/tasks/{prefix}.json", task_data)
            packet = save(root, f"case/rounds/work/{prefix}.json", {"context": reference, "task": task})
            for suffix, template in (("evidence", "collect_litigation_evidence"), ("assessment", "assess_litigation_hypothesis"), ("review", "review_litigation_finding")):
                key = f"{h['id']}-{suffix}"
                steps.append({"id": key, "template": template, "needs": previous, "input": {"task": packet}})
                previous = [key]
        task = save(root, f"case/rounds/tasks/summary-{revision+1:02d}.json", {"revision": revision+1})
        packet = save(root, f"case/rounds/work/summary-{revision+1:02d}.json", {"context": reference, "task": task})
        steps.append({"id": "summarize", "template": "summarize_litigation_round", "needs": previous, "input": {"task": packet}})
        result = {"done": False, "tasks": steps, "rationale": f"Execute committed litigation enquiries for round {revision+1}", "evidence_refs": []}
    save(root, name, {"context": reference, "plan": result, "output": output})
    return result


def summarize(context, inputs):
    from .state import read_seal
    work = inputs["input"]
    revision = work["_child"]["revision"]
    saved = read(context.store.path(f"case/rounds/plan-{revision:02d}.json"))
    if saved["context"] != work["seed"]["context"] or saved["plan"]["done"] is not True:
        raise ValueError("A litigation summary requires its terminal domain plan")
    output = saved["output"]
    terminal = read_seal(context, output["terminal"], "terminal")
    if terminal["context"] != saved["context"] or terminal["revision"] != revision:
        raise ValueError("Litigation terminal authority changed")
    from .state import verify_files
    verify_files(context, [terminal["investigation"], terminal["checkpoint"]])
    return output
