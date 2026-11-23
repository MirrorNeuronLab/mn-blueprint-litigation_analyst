"""Route the next investigation round from collected evidence and independent review."""
import re

from mn_sdk.blueprint.memory import digest, runtime_text_memory

from .claim_memory import _notes
from .evidence_admission import review_closure
from .gap_work import classify
from .round_state import load, read, save
from .source_query import PRINCIPAL


COUNSEL_ROUTES = {"ready_for_counsel", "counsel_follow_up", "handling_review"}
FAMILY = "litigation_enquiry_review"


def feedback(task, assessment, review, collected, independent, documents):
    hypothesis = assessment["hypothesis"]
    proposed = {f["id"] for f in assessment["report"]["findings"]}
    withheld = sorted(proposed.difference(review["accepted_ids"]))
    work = [classify(item, documents) for item in assessment["work_items"]]
    types = {item["work_type"] for item in work}
    previously_requested = {item["requested_record"].casefold().strip()
                            for item in task.get("review_direction", {}).get("next_records", [])}
    def needs_internal_search(item):
        request = item["requested_record"].casefold().strip()
        external_action = re.match(r"(?:interview|depose|subpoena|contact)\s+(?:the|a|an|all|each)\b", request)
        return item["work_type"] == "customer_follow_up" and request not in previously_requested and not external_action

    if "handling_review" in types:
        route = "handling_review"
    elif withheld:
        route = "recheck_finding"
    elif hypothesis["contradictory_evidence"] or hypothesis["status"] == "contradicted":
        route = "compare_accounts"
    elif "internal_reread" in types:
        route = "reread_record"
    elif any(needs_internal_search(item) for item in work):
        route = "trace_gap"
    elif "customer_follow_up" in types:
        route = "counsel_follow_up"
    elif hypothesis["outstanding_enquiries"] or hypothesis["status"] in {"proposed", "inconclusive"}:
        route = "trace_gap"
    else:
        route = "ready_for_counsel"

    searches = []
    for record in collected["records"] + [independent]:
        if record["purpose"] not in {"support", "counter", "independent_counter"}:
            continue
        arguments = record["action"].get("arguments", {})
        query = arguments.get("arguments", {}).get("query") or record["action"].get("query")
        searches.append({"purpose": record["purpose"], "query": query,
                        "passages": len(record["result"]["passages"]), "reused": bool(record["result"].get("reused"))})
    return {"enquiry_version": task["prefix"], "id": hypothesis["id"], "route": route,
            "counsel_issue_ids": assessment["counsel_issue_ids"], "searches": searches,
            "accepted_ids": review["accepted_ids"], "withheld_ids": withheld,
            "review_issues": review["issues"], "next_records": [
                {k: item[k] for k in ("work_type", "requested_record", "closure_condition")} for item in work]}


def publish(root, frozen, assessment, review, reference):
    item = review["feedback"]
    prefix = item["enquiry_version"]
    marker = f"case/rounds/{prefix}-review-memory.json"
    if (root / marker).exists():
        return
    memory = runtime_text_memory(frozen["config"], principal=PRINCIPAL, scope=frozen["memory_scope"])
    if memory is None:
        return
    try:
        from mn_context_engine_sdk.intelligent_system import RuntimeRecord
        claim = read(root / f"case/rounds/{prefix}-memory-graph.json")["claim"]
        identifier = "case-reviewed-" + digest([frozen["indexed"], reference])
        h = assessment["hypothesis"]
        record = RuntimeRecord(identifier, "Independent enquiry review", review["reviewed_at"],
            "investigative_lead_for_counsel_review",
            {"memory_family": FAMILY, "case_snapshot": frozen["indexes"]["hashes"]["sources.json"],
             "case_binding": digest([frozen["memory_scope"], frozen["indexed"]]),
             "enquiry_version": prefix, "review_route": item["route"], "assessment_status": h["status"]},
            notes=_notes({"question": h["question"], "assessment": h["assessment"], "alternatives": h["alternatives"],
                          "open_questions": h["outstanding_enquiries"], **item}),
            relations=((identifier, "REVIEWS", claim["source_id"].removeprefix("run:")),), kind="decision")
        receipt = memory.record(record, event_id=identifier, upstream=[{"review": reference}], allow=[PRINCIPAL])
        save(root, marker, receipt)
    finally:
        memory.close()


def recall_stages(frozen, prior, limit):
    filters = [
        {"field": "memory_family", "op": "eq", "value": FAMILY},
        {"field": "case_binding", "op": "eq", "value": digest([frozen["memory_scope"], frozen["indexed"]])},
        {"field": "enquiry_version", "op": "in", "value": [row["enquiry_version"] for row in prior]},
    ]
    return [{"mode": "analytical", "analytical": {
        "operation": "recent", "timestamp_field": "timestamp", "limit": limit, "filters": filters}}]


def planning_item(feedback):
    """Give the planner the disposition even when optional recall has no room."""
    from .supervision import compact
    return {**{k: feedback[k] for k in ("id", "enquiry_version", "route", "counsel_issue_ids", "next_records")},
            "review_concerns": [compact(issue, 300) for issue in feedback["review_issues"][:2]],
            "review_concern_count": len(feedback["review_issues"]),
            "searches": [{**row, "query": compact(row["query"], 250)} for row in feedback["searches"]]}


def follow_up_leads(root, item):
    """Carry complete counter-search groups back to collection for a frozen reread."""
    ref = item["counter_search_ref"]
    if ref["path"] != f"case/rounds/{item['enquiry_version']}-review-search.json":
        raise ValueError("Follow-up lead belongs to another enquiry")
    result = load(root, ref)["result"]
    if result.get("unresolved"):
        return []
    leads = []
    for group in result.get("support_groups", []):
        try:
            spans = review_closure(result["passages"], [{"result": result}], group["source_evidence_ids"])
        except ValueError:
            continue  # An incomplete component cannot become evidence in a later round.
        if 0 < len(spans) <= 12:
            lead = [{k: span[k] for k in ("source_id", "content_sha256", "start_offset", "end_offset")}
                    for span in spans]
            if lead not in leads:
                leads.append(lead)
            if len(leads) == 2:
                break
    return leads
