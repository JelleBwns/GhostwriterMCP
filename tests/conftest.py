import json
import os
import socket

import pytest

from gw_reporting.config import settings

# Isolate imports as well as individual tests from the private workstation .env.
DEFAULT_TOOLS = [
    "gw_list_projects",
    "gw_get_project",
    "gw_list_reports",
    "gw_get_report",
    "gw_list_findings",
    "gw_search_finding_library",
    "gw_get_finding_options",
    "gw_create_finding",
    "gw_update_finding",
]
os.environ["GW_REPORTING_ENV_FILE"] = "/tmp/ghostwriter-tests-missing.env"
os.environ["GW_ENABLED_TOOLS"] = json.dumps(DEFAULT_TOOLS)
os.environ["GW_BASE_URL"] = "https://ghostwriter.example.test"
os.environ["GW_TOKEN"] = "test-token"
os.environ["ALLOWED_PROJECTS"] = "[49]"
os.environ["ALLOWED_CLIENTS"] = "[]"
os.environ["GW_DISABLED_TOOLS"] = "[]"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    # Never read real workstation credentials or contact the real instance in tests.
    monkeypatch.setenv("GW_REPORTING_ENV_FILE", str(tmp_path / "unused.env"))
    monkeypatch.setenv("GW_BASE_URL", "https://ghostwriter.example.test")
    monkeypatch.setenv("GW_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_PROJECTS", "[49]")
    monkeypatch.setenv("ALLOWED_CLIENTS", "[]")
    monkeypatch.setenv("GW_DISABLED_TOOLS", "[]")
    monkeypatch.setenv("GW_TLS_VERIFY", "true")
    monkeypatch.delenv("FINDING_TYPE_ID", raising=False)
    settings.cache_clear()

    def deny_network(*args, **kwargs):
        raise AssertionError("Real network access is forbidden in tests")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    yield
    settings.cache_clear()
