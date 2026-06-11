"""Sanity checks for the parallel dev Docker Compose overlay.

The dev overlay (docker/dev.yml) shifts host ports and bind-mounts ./data-dev
so a second stack can run beside production. These tests merge base + overlay
YAML without invoking docker compose.
"""

import copy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

BASE = ROOT / "docker-compose.yml"
DEV_OVERLAY = ROOT / "docker" / "dev.yml"


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    # Compose merge tags are not standard YAML; strip for pytest parsing.
    text = text.replace("ports: !override", "ports:")
    return yaml.safe_load(text)


def _deep_merge_service(base_svc: dict, overlay_svc: dict) -> dict:
    """Approximate compose merge for the keys dev.yml touches."""
    result = copy.deepcopy(base_svc)
    for key, value in overlay_svc.items():
        if key == "environment":
            base_env = result.get("environment") or []
            if isinstance(base_env, list):
                env_map = {}
                for item in base_env:
                    if isinstance(item, str) and "=" in item:
                        k, v = item.split("=", 1)
                        env_map[k] = v
                if isinstance(value, dict):
                    env_map.update(value)
                else:
                    for item in value:
                        if isinstance(item, str) and "=" in item:
                            k, v = item.split("=", 1)
                            env_map[k] = v
                result["environment"] = [f"{k}={v}" for k, v in env_map.items()]
            else:
                result["environment"] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_service(result[key], value)
        elif isinstance(value, list) and key == "environment":
            result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _merge_dev_overlay(base: dict, overlay: dict) -> dict:
    expected = copy.deepcopy(base)
    for name, overlay_svc in overlay["services"].items():
        expected["services"][name] = _deep_merge_service(
            expected["services"][name], overlay_svc
        )
    return expected


@pytest.fixture(scope="module")
def dev_overlay():
    assert DEV_OVERLAY.is_file(), "docker/dev.yml must exist"
    return _load(DEV_OVERLAY)


@pytest.fixture(scope="module")
def merged_dev(base):
    overlay = _load(DEV_OVERLAY)
    return _merge_dev_overlay(base, overlay)


@pytest.fixture(scope="module")
def base():
    return _load(BASE)


def test_dev_overlay_declares_port_override():
    text = DEV_OVERLAY.read_text(encoding="utf-8")
    assert "ports: !override" in text
    assert text.count("ports: !override") == 4


def test_odysseus_uses_data_dev_volumes(merged_dev):
    vols = merged_dev["services"]["odysseus"]["volumes"]
    assert any("./data-dev:/app/data" in v for v in vols)
    assert any("./logs-dev:/app/logs" in v for v in vols)
    assert not any("./data:/app/data" in v for v in vols)


def test_odysseus_dev_port(merged_dev):
    ports = merged_dev["services"]["odysseus"]["ports"]
    assert any("APP_PORT:-7001" in p and ":7000" in p for p in ports)


def test_bundled_service_dev_host_ports(merged_dev):
    chromadb_ports = merged_dev["services"]["chromadb"]["ports"]
    searxng_ports = merged_dev["services"]["searxng"]["ports"]
    ntfy_ports = merged_dev["services"]["ntfy"]["ports"]
    assert any("8101:8000" in p for p in chromadb_ports)
    assert any("8081:8080" in p for p in searxng_ports)
    assert any("8092:80" in p for p in ntfy_ports)


def test_searxng_dev_base_url(dev_overlay):
    assert dev_overlay["services"]["searxng"]["environment"]["SEARXNG_BASE_URL"] == (
        "http://localhost:8081/"
    )


def test_ntfy_dev_base_url(dev_overlay):
    assert dev_overlay["services"]["ntfy"]["environment"]["NTFY_BASE_URL"] == (
        "http://localhost:8092"
    )


def test_odysseus_dev_restart_policy(dev_overlay):
    assert dev_overlay["services"]["odysseus"]["restart"] == "no"
