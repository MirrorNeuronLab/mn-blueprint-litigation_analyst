"""Check the Docker recipe after the SDK stages the blueprint's dependencies."""
from pathlib import Path

import pytest
from mn_sdk.blueprints import compile_blueprint, read_blueprint
from mn_sdk.submission_preparation import stage_skill_dependency_payloads_for_manifest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = "/tmp/mn-skill-runtime"


@pytest.mark.parametrize("local", [True, False], ids=["local-source", "registry"])
def test_worker_installs_staged_requirements_once(tmp_path, local):
    manifest = compile_blueprint(read_blueprint(ROOT)).manifest
    if local:
        source = tmp_path / "sample_skill"
        source.mkdir()
        (source / "pyproject.toml").write_text('[project]\nname="sample-skill"\nversion="1.0"\n')
        manifest.setdefault("metadata", {})["mn_local_skill_dependencies"] = {
            "sources": [{"package": "sample-skill", "source": str(source), "target": ".mn-local-skills/sample_skill"}]
        }

    payloads = {}
    stage_skill_dependency_payloads_for_manifest(manifest, payloads, bundle_dir=ROOT)
    recipe = payloads["docker_worker/Dockerfile"].decode().splitlines()
    requirements = payloads["requirements.txt"].decode().splitlines()
    assert any(line.startswith("duckdb") for line in requirements)
    installs = [i for i, line in enumerate(recipe) if "pip install " in line and " -r " in line]
    assert len(installs) == 1
    install = installs[0]
    assert f"-r {RUNTIME}/requirements.txt" in recipe[install]
    copies = {line.split()[-1]: line.split()[1] for line in recipe[:install] if line.startswith("COPY ")}
    assert copies[f"{RUNTIME}/requirements.txt"] == "requirements.txt"

    include = f"-r {RUNTIME}/local-requirements.txt"
    assert (include in requirements) == local
    if local:
        assert copies[f"{RUNTIME}/local-requirements.txt"] == "local-requirements.txt"
        paths = payloads["local-requirements.txt"].decode().splitlines()
        assert paths == [f"{RUNTIME}/local/sample_skill"]
        assert f"{copies[paths[0]]}/pyproject.toml" in payloads
    else:
        assert "local-requirements.txt" not in payloads
