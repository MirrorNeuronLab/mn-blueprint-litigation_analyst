"""Reopen an original stored by an earlier investigation of the same case."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("filename,spans", [
    ("notice.txt", ()), ("notice.pdf", ((1, 0, 6), (2, 7, 14))),
])
def test_new_run_reuses_exact_persisted_original(tmp_path, monkeypatch, filename, spans):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "payloads"))
    from domain import source_query
    from domain.models import CaseDocument
    from mn_sdk.context.sources import SourceQuerySession
    from mn_sdk.context_session.contracts import digest

    text = "Notice\nReceipt"
    normalized = hashlib.sha256(text.encode()).hexdigest()
    original_bytes = b"original PDF bytes" if spans else text.encode()
    original = hashlib.sha256(original_bytes).hexdigest()
    doc = CaseDocument("case:" + filename, filename, "application/pdf" if spans else "text/plain",
                       original, len(original_bytes), text, "case", page_spans=spans)
    principal = source_query.PRINCIPAL
    # A prior publication used native tuples on input. Its identity and stored
    # metadata went through the SDK's JSON transport.
    upstream = [{**asdict(doc), "text": None, "normalized_sha256": normalized, "original_sha256": original}]
    identity = digest(["original-source", filename, normalized, upstream, [principal]])
    stored = json.loads(json.dumps({
        "revision": "first-revision", "text": text, "source_is_current": True, "dependency_status": "valid",
        "metadata": {"kind": "input", "event_id": identity, "allow": [principal], "roles": [],
                     "upstream": [*upstream, {"source_path": filename, "source_sha256": normalized}]},
    }))

    def read(source_id):
        assert source_id == "job:" + identity
        return stored

    def session(config, *, principal, scope):
        client = SimpleNamespace(_scope=(scope["job_id"], scope["run_id"], principal),
                                 read_complete=read, close=lambda: None)
        return SourceQuerySession(scope=scope, principal=principal, client=client)

    monkeypatch.setattr(source_query, "source_text_query", session)

    def publish(run):
        root = tmp_path / run
        (root / "case").mkdir(parents=True)
        inventory = {"sources_sha256": normalized, "files": [{"path": filename, "sha256": original}]}
        (root / "case/source_inventory.json").write_text(json.dumps(inventory))
        source_query.publish(SimpleNamespace(store=SimpleNamespace(run_dir=root), config={}), [doc],
                             {"job_id": "matter", "run_id": run})
        return json.loads((root / "case/source-query.json").read_text())["source_records"][doc.source_id]

    ref = publish("second-run")
    assert (ref["source_id"], ref["revision"]) == ("job:" + identity, "first-revision")
    stored["metadata"]["upstream"][0]["original_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="immutable source publication differs"):
        publish("changed-provenance")
