"""Legal-record adapters for the shared temporal graph skill; no mental-state inference."""
from datetime import timedelta, timezone
from email import policy
from email.parser import Parser
from email.utils import getaddresses, parsedate_to_datetime
import hashlib
import json
import re

from mn_temporal_graph_skill import compare_time, distinct_occurrences, fingerprint, temporal_path

UNKNOWN_TIME = {"earliest": None, "latest": None}
VIEWS = {"temporal_communication_paths": "Source-backed, directed addressing paths with strict temporal ordering."}


def email_time(raw):
    """Retain the source's precision/offset. Unzoned dates never acquire a timezone."""
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        value = None
    if value is None or value.tzinfo is None:
        return {"time": dict(UNKNOWN_TIME), "display": raw or "Date unavailable",
                "precision": "unresolved", "basis": "Source Date header; timezone/order unresolved"}
    value = value.astimezone(timezone.utc)
    seconds_supplied = bool(re.search(r"\d{1,2}:\d{2}:\d{2}", raw))
    latest = value if seconds_supplied else value + timedelta(seconds=59, microseconds=999999)
    return {"time": {"earliest": value.isoformat(), "latest": latest.isoformat()}, "display": raw,
            "precision": "second" if seconds_supplied else "minute",
            "basis": "Represented Date header; transmission not independently verified"}


def project(documents, matter):
    """Only top-level headers create communication edges; quotes never create events."""
    events, nodes, edges = [], {}, []
    for document in documents:
        if document.media_type != "message/rfc822" or document.text is None:
            continue
        message = Parser(policy=policy.default).parsestr(document.text)
        fields = {name: sorted({address.strip().casefold() for _, address in
            getaddresses(message.get_all(name, [])) if "@" in address}) for name in ("From", "To", "Cc", "Bcc")}
        for name in fields:
            for display, address in getaddresses(message.get_all(name, [])):
                address = address.strip().casefold()
                if address not in fields[name]:
                    continue
                node = nodes.setdefault(address, {"id": address, "label": address, "names": [],
                    "kind": "address", "identity_status": "Address observed; person mapping unresolved"})
                if display and display not in node["names"]:
                    node["names"].append(display)
        timing = email_time(str(message.get("Date", "")))
        message_id = str(message.get("Message-ID", "")).strip()
        valid_id = message_id.startswith("<") and message_id.endswith(">") and not any(c.isspace() for c in message_id)
        header_end = document.text.find("\n\n")
        header_end = len(document.text) if header_end < 0 else header_end
        evidence_id = hashlib.sha256(f"{document.source_id}|{document.content_sha256}|0|{header_end}".encode()).hexdigest()[:32]
        ref = {"source_id": document.source_id, "content_sha256": document.content_sha256,
               "start_offset": 0, "end_offset": header_end, "evidence_id": evidence_id,
               "text": document.text[:header_end]}
        semantic = {"headers": fields, "subject": str(message.get("Subject", "")),
                    "normalized_sha256": document.content_sha256, "message_id": message_id}
        event = {"id": "E-" + fingerprint([document.source_id, document.content_sha256])[:16],
            "assertion_id": document.source_id, "kind": "event", "entity": message_id or document.source_id,
            "claim_class": "observed", "capability": "top_level_email_headers", "fields": semantic,
            "access_scope": document.access_scope,
            **timing, "source_ids": [document.source_id], "evidence_refs": [ref],
            "occurrence_key": fingerprint([matter, message_id]) if valid_id else None,
            "lane": "Communications", "title": str(message.get("Subject", "")) or "Recorded email",
            "qualification": "Addressing does not establish delivery, reading, agreement, or knowledge."}
        events.append(event)
    # A Message-ID collision with differing source semantics remains unresolved.
    groups = {}
    for event in events:
        if event["occurrence_key"]:
            groups.setdefault(event["occurrence_key"], []).append(event)
    for group in groups.values():
        if len({fingerprint(e["fields"]) for e in group}) > 1:
            for event in group:
                event["conflicts"] = [e["id"] for e in group if e is not event]
    for event in events:
        for sender in event["fields"]["headers"]["From"]:
            for field in ("To", "Cc", "Bcc"):
                for recipient in event["fields"]["headers"][field]:
                    edges.append({"id": "R-" + fingerprint([event["id"], sender, recipient, field])[:16],
                        "source": sender, "target": recipient, "relation": field.upper(),
                        "event_id": event["id"], "host_epoch_id": matter,
                        "scope": event["access_scope"],
                        "claim_class": "observed", "kind": "recorded_addressing", "time": event["time"],
                        "display_time": event["display"], "evidence_refs": event["evidence_refs"],
                        "conflicts": event.get("conflicts", []), "qualification": event["qualification"]})
    counts = distinct_occurrences(events)
    for event in events:
        event["metric_occurrence_id"] = event["occurrence_key"] if event["occurrence_key"] in counts["occurrence_ids"] else None
    return {"version": "mn.litigation.temporal.v1", "matter": matter, "events": events,
            "nodes": sorted(nodes.values(), key=lambda n: n["id"]), "edges": edges,
            "message_count": counts, "source_record_count": len(events),
            "count_definition": "Distinct consistent Message-ID values within this matter. Missing/conflicting IDs excluded; duplicate copies retained as source records. Top-level headers only."}


def paths(projection, seeds, scope, *, target=None, relations=("TO", "CC", "BCC"), max_hops=4, max_edges=49):
    allowed = {n["id"] for n in projection["nodes"]}
    if not seeds or len(seeds) > 16 or not set(seeds) <= allowed or target is not None and target not in allowed:
        raise ValueError("Temporal paths require 1..16 authorized address seeds and an authorized target")
    edges = [e for e in projection["edges"] if e["scope"] == scope]
    def fetch(frontier, kinds, direction, capacity):
        matching = [e for e in edges if e["source"] in frontier and e["relation"] in kinds]
        return {"edges": matching[:capacity-1], "complete": len(matching) < capacity, "unresolved": []}
    result = temporal_path(seeds, relations, fetch, host_epoch_id=projection["matter"],
        scope=scope, max_hops=max_hops, max_edges=max_edges)
    if target is not None:
        for key in ("paths", "partial_paths", "rejected_paths"):
            result[key] = [p for p in result[key] if p["target"] == target]
        if not result["unresolved"]:
            result["status"] = "MATCHED" if result["paths"] else "PARTIAL" if result["partial_paths"] else "NOT_MATCHED"
    # Even an ordered path describes addressing, not transfer of a material or knowledge.
    result["qualification"] = "Chronology of recorded addressing only. No continuous employment, material transfer, receipt, or mental state is established. Unknown clocks/identities remain unresolved."
    result["identity_status"] = "Address-level path; people are not automatically merged."
    return result


def compare(projection, earlier_id, later_id):
    events = {e["id"]: e for e in projection["events"]}
    if earlier_id not in events or later_id not in events:
        raise ValueError("Unknown authorized chronology event")
    a, b = events[earlier_id], events[later_id]
    return {"earlier": a["id"], "later": b["id"], **compare_time(a, b),
            "evidence_refs": a["evidence_refs"] + b["evidence_refs"], "qualification": "Temporal order does not establish causation."}


def path_evidence_ids(path, passages):
    """Bind every addressing edge to its exact, available header passage."""
    edges = path.get("edges") if isinstance(path, dict) else None
    if not isinstance(edges, list) or not edges:
        return ()
    ids = []
    for edge in edges:
        refs = edge.get("evidence_refs") if isinstance(edge, dict) else None
        if not isinstance(refs, list) or not refs:
            return ()
        for ref in refs:
            eid = ref.get("evidence_id") if isinstance(ref, dict) else None
            passage = passages.get(eid) if isinstance(eid, str) and eid else None
            if passage is None or any(k not in ref or k not in passage or ref[k] != passage[k]
                    for k in ("source_id", "content_sha256", "start_offset", "end_offset", "text")):
                return ()
            ids.append(eid)
    ids = list(dict.fromkeys(ids))
    if "source_evidence_ids" in path and path["source_evidence_ids"] != ids:
        return ()
    return tuple(ids)


def walk(case, corpus, passages, view, config):
    projection = project(tuple(corpus.scan()), json.loads((case / "source_inventory.json").read_text())["repository_id"])
    selected = {p["source_id"] for p in passages}
    seeds = list(dict.fromkeys(e["source"] for e in projection["edges"] if e["evidence_refs"][0]["source_id"] in selected))[:16]
    if not seeds:
        return {"status": "entity_unresolved", "paths": [], "passages": [], "support_groups": [],
                "unresolved": ["No addressed-message seeds in the selected passages"], "exhaustive": False}
    result = paths(projection, seeds, corpus.access_scope)
    headers = {ref["evidence_id"]: ref for event in projection["events"] for ref in event["evidence_refs"]}
    refs, groups = {}, []
    for kind in ("paths", "partial_paths"):
        bound = []
        for path in result[kind]:
            ids = list(path_evidence_ids(path, headers))
            if not ids:
                continue
            bound.append({**path, "source_evidence_ids": ids})
            refs.update((eid, headers[eid]) for eid in ids)
            groups.append({"id": f"{view}:{len(groups)}", "source_evidence_ids": ids,
                           "complete": True, "required": False})
        omitted = len(result[kind]) - len(bound)
        if omitted:
            result["unavailable_graph_paths"] = result.get("unavailable_graph_paths", 0) + omitted
        result[kind] = bound
    if result.get("unavailable_graph_paths"):
        result["unresolved"].append("unverified_temporal_path")
        result.update(status="INCOMPLETE_SEARCH", exhaustive=False)
    result.update(view=view, passages=list(refs.values()), support_groups=groups)
    return result
