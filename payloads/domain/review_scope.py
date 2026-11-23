"""Bounded attorney review profiles, independent of runtime scheduling."""
from copy import deepcopy


# Each objective directs investigation within the supplied sources.
OBJECTIVES = {
    "investigation": "Follow the review goal and test the strongest ordinary alternative.",
    "discovery": "Map the requested records to cleared sources, gaps and document families. Identify the next record and closure test for counsel.",
    "case_strategy": "Test competing accounts of a material event and distinguish the evidence for and against each account.",
    "witness_preparation": "Compare an attributed statement with a dated exhibit. Identify a neutral witness question that would resolve the difference.",
    "court_preparation": "Test each proposed factual proposition against its precise record citation and the strongest contrary passage. Leave authority and filing decisions to counsel.",
}


def limits(config):
    profile = config.get("review", {}).get("profile", "standard")
    if profile not in {"adaptive", "first_pass", "standard"}:
        raise ValueError("review.profile must be adaptive, first_pass or standard")
    objective = config.get("review", {}).get("objective", "investigation")
    if objective not in OBJECTIVES:
        raise ValueError("Unknown litigation review objective")
    settings = config["dynamic_investigation"]
    first = profile == "first_pass"
    batch_size = settings["hypotheses_per_round"]
    plan_size = settings.get("max_review_questions", batch_size)
    # The first round can include questions added by the reviewer. Later rounds
    # retain their normal batch size and independent review for each answer.
    ceiling = min(config["investigation"]["max_model_decisions"], config["context_memory"]["policy"]["max_calls"],
                  (6 if first else 16) + 2 * max(0, plan_size - batch_size))
    # Reserve one drafting decision, one search design for edits, and two decisions per answer.
    available = min(plan_size, max(0, (ceiling - 2) // 2))
    return {"profile": profile, "objective": objective,
            "max_rounds": min(settings["max_rounds"], 1 if first else 3),
            "hypotheses_per_round": min(batch_size, available), "max_review_questions": available,
            "seconds": min(config["investigation"]["max_investigation_seconds"], 600 if first else 99999),
            "max_decisions": ceiling,
            "relationship_mode": config["source_relationships"]["mode"] if profile == "standard" else "structural",
            "relationship_call_ceiling": config["source_relationships"]["max_calls"] if profile == "standard" else 0,
            "definition": "Decision ceilings exclude provider transport/repair attempts; elapsed limits are checked at planning boundaries. Ranked retrieval is not exhaustive."}


def decision_config(config):
    result = deepcopy(config)
    if "review" in config:
        ceiling = limits(config)["max_decisions"]
        result["context_memory"]["policy"].update(max_calls=min(result["context_memory"]["policy"]["max_calls"], ceiling), final_call_reserve=0)
    return result
