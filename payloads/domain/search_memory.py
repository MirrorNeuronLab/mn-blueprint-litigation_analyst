"""Reuse a collector's exact search against the same frozen case index."""
from datetime import datetime, timezone

from mn_sdk.blueprint.memory import digest, runtime_text_memory
from mn_sdk.blueprint.storage import CommittedJsonStore

from .claim_memory import _notes
from .source_query import PRINCIPAL


def _reuse(store, result, receipt):
    original = result.get("receipt", {}).get("search_result_ref")
    if original:
        store.read_bytes(original)
    return {**result, "reused": True, "search_memory": receipt}


def collect(root, frozen, arguments, search):
    memory = runtime_text_memory(frozen["config"], principal=PRINCIPAL, scope=frozen["memory_scope"])
    if memory is None:
        return search()
    try:
        key = digest([memory.scope, PRINCIPAL, frozen["indexed"], arguments])
        record_id = "case-search-" + key
        store = CommittedJsonStore(root)
        base = "case/rounds/searches/" + key
        path, marker = base + ".json", base + "-memory.json"
        with store.locked(record_id):
            if store.path(marker).is_file():
                receipt = store.read_path(marker)
                source_id = "run:" + record_id
                memory.check()
                current = memory.client.read_complete(source_id, revision=receipt["revision"])
                if (receipt["source_id"] != source_id or current["revision"] != receipt["revision"]
                        or not current["source_is_current"] or current["dependency_status"] != "valid"):
                    raise ValueError("Saved case search is no longer current")
                ref = current["metadata"]["upstream"][0]["search_result"]
                if ref["path"] != path:
                    raise ValueError("Saved case search belongs to another request")
                packet = store.read(ref)
                return _reuse(store, packet["result"], receipt)

            # Keep the first observation durable before publication. A retry after
            # a lost Membrane reply publishes the same record and clock.
            resuming = store.path(path).is_file()
            if resuming:
                packet = store.read_path(path)
            else:
                packet = {"result": search(), "observed_at": datetime.now(timezone.utc).isoformat()}
            ref = store.commit(path, packet).to_dict()
            result = packet["result"]
            from mn_context_engine_sdk.intelligent_system import RuntimeRecord
            record = RuntimeRecord(record_id, "Litigation evidence search", packet["observed_at"],
                "ranked_search_navigation", {"memory_family": "litigation_search",
                    "case_snapshot": frozen["indexes"]["hashes"]["sources.json"],
                    "passage_count": len(result["passages"]), "search_status": result["status"],
                    "unresolved_count": len(result.get("unresolved", []))},
                notes=_notes({"query": arguments["query"], "top_k": arguments["top_k"],
                              "coverage": "Ranked results within the frozen case scope."}))
            receipt = memory.record(record, event_id=record_id,
                                    upstream=[{"search_result": ref}], allow=[PRINCIPAL])
            pinned = {k: receipt[k] for k in ("source_id", "revision")}
            if pinned["source_id"] != "run:" + record_id or not pinned["revision"]:
                raise ValueError("Membrane returned an unexpected case search receipt")
            store.commit(marker, pinned)
            return _reuse(store, result, pinned) if resuming else result
    finally:
        memory.close()
