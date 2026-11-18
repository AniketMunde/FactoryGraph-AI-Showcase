"""Static packaging checks; these explicitly do not claim containers were started."""

from pathlib import Path

import pytest
import yaml


def test_compose_exposure_secrets_and_immutable_mounts():
    config = yaml.safe_load(Path("deployment/docker-compose.yml").read_text())
    assert "ports" not in config["services"]["neo4j"]
    for name in ["api", "dashboard"]:
        service = config["services"][name]
        assert all(p.startswith("127.0.0.1:") for p in service["ports"])
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert service["secrets"]
    for mount in config["services"]["api"]["volumes"]:
        assert mount.endswith(":ro") and ".venv" not in mount
    assert config["networks"]["internal"]["internal"]
    assert "neo4j_password" in config["services"]["neo4j"]["secrets"]


def test_container_sources_are_allowlisted_and_cpu_only():
    ignores = Path(".dockerignore").read_text()
    assert ignores.startswith("**\n") and "!src/**" in ignores
    for name in ["api", "dashboard"]:
        docker = Path(f"deployment/{name}/Dockerfile").read_text()
        assert "USER 10001" in docker and "HEALTHCHECK" in docker
        assert "COPY . " not in docker and "torch" not in docker.lower()
    locks = (
        Path("requirements/phase7-api.lock").read_text()
        + Path("requirements/phase7-dashboard.lock").read_text()
    )
    assert "torch==" not in locks and "transformers==" not in locks


def test_bootstrap_cannot_target_original_local_database(monkeypatch):
    pytest.importorskip("fastapi")
    from factorygraph.phase7.bootstrap import initialize

    monkeypatch.setenv("FACTORYGRAPH_NEO4J_URI", "bolt://127.0.0.1:17687")
    monkeypatch.setenv("FG7_CONTAINER", "1")
    with pytest.raises(ValueError, match="restricted"):
        initialize()
