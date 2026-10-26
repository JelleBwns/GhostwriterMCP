from unittest.mock import AsyncMock

import pytest
from fastmcp import Client

from gw_reporting import queries as q
from gw_reporting.config import Settings, settings
from gw_reporting.direct import DirectAuthoring
from gw_reporting.ghostwriter import Ghostwriter
from gw_reporting.mcp import CONVENIENCE, gw_list_projects
from gw_reporting.registry import build_server, effective_tools
from gw_reporting.reporting import Reporting
from gw_reporting.schemas import (
    DomainError,
    ReportChanges,
    ReportFindingChanges,
    ReportFindingContent,
    ReportTemplateSelection,
)


@pytest.mark.parametrize(
    "allow,deny,expected",
    [
        (None, None, set(CONVENIENCE)),
        ([], [], set(CONVENIENCE)),
        (["gw_create_finding"], None, {"gw_create_finding"}),
        (
            None,
            ["gw_create_report", "gw_delete_finding"],
            set(CONVENIENCE) - {"gw_create_report", "gw_delete_finding"},
        ),
        (["gw_create_finding", "gw_create_report"], ["gw_create_report"], {"gw_create_finding"}),
        (None, list(CONVENIENCE), set()),
    ],
)
async def test_public_tool_exposure_for_allow_and_blacklists(allow, deny, expected):
    server = build_server(CONVENIENCE, allow, deny)
    async with Client(server) as client:
        assert {t.name for t in await client.list_tools()} == expected
        if "gw_create_report" not in expected:
            with pytest.raises(Exception):
                await client.call_tool(
                    "gw_create_report", {"project_id": 49, "title": "Must not run"}
                )


@pytest.mark.parametrize(
    "allow,deny",
    [
        (["typo"], None),
        (None, ["typo"]),
        ([], ["gw_delete_project"]),
        (["gw_create_finding"], ["*"]),
        ("gw_create_finding", None),
        (None, "gw_delete_finding"),
    ],
)
def test_invalid_tool_policy_fails_closed(allow, deny):
    with pytest.raises(ValueError):
        effective_tools(CONVENIENCE, allow, deny)


def test_missing_policy_settings_default_to_all_tools(monkeypatch):
    monkeypatch.delenv("GW_ENABLED_TOOLS", raising=False)
    monkeypatch.delenv("GW_DISABLED_TOOLS", raising=False)
    cfg = Settings(_env_file=None)
    assert effective_tools(CONVENIENCE, cfg.gw_enabled_tools, cfg.gw_disabled_tools) == set(
        CONVENIENCE
    )


@pytest.mark.parametrize(
    "projects,clients,expected",
    [
        ([], [], {}),
        ([49], [], {"id": {"_in": [49]}}),
        ([], [7], {"clientId": {"_in": [7]}}),
        ([49], [7], {"id": {"_in": [49]}, "clientId": {"_in": [7]}}),
    ],
)
def test_project_listing_filter_intersects_scope_lists(monkeypatch, projects, clients, expected):
    monkeypatch.setattr(settings(), "allowed_projects", projects)
    monkeypatch.setattr(settings(), "allowed_clients", clients)
    assert Ghostwriter.project_filter() == expected


@pytest.mark.parametrize("client_id", [7, "7"])
async def test_project_in_allowed_client_is_accepted(monkeypatch, client_id):
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    client = Ghostwriter()
    call = AsyncMock(return_value={"project_by_pk": {"id": 49, "clientId": client_id}})
    monkeypatch.setattr(client, "execute", call)
    assert (await client.project(49))["id"] == 49
    call.assert_awaited_once_with(q.PROJECT, {"id": 49})


@pytest.mark.parametrize("client_id", [8, None, "invalid"])
async def test_wrong_or_unverifiable_client_is_denied(monkeypatch, client_id):
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    client = Ghostwriter()
    monkeypatch.setattr(
        client,
        "execute",
        AsyncMock(return_value={"project_by_pk": {"id": 49, "clientId": client_id}}),
    )
    with pytest.raises(DomainError, match="client scope"):
        await client.project(49)


async def test_client_only_scope_allows_its_other_projects(monkeypatch):
    monkeypatch.setattr(settings(), "allowed_projects", [])
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    client = Ghostwriter()
    monkeypatch.setattr(
        client, "execute", AsyncMock(return_value={"project_by_pk": {"id": 100, "clientId": 7}})
    )
    assert (await client.project(100))["id"] == 100


async def test_project_scope_is_not_bypassed_by_client_allowance(monkeypatch):
    monkeypatch.setattr(settings(), "allowed_projects", [49])
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    client = Ghostwriter()
    call = AsyncMock(return_value={"project_by_pk": {"id": 100, "clientId": 7}})
    monkeypatch.setattr(client, "execute", call)
    with pytest.raises(DomainError, match="engagement scope"):
        await client.project(100)
    call.assert_not_awaited()


async def test_project_list_tool_sends_both_filters(monkeypatch):
    from gw_reporting.mcp import gw

    monkeypatch.setattr(settings(), "allowed_projects", [49])
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    page = AsyncMock(return_value=[])
    monkeypatch.setattr(gw, "page", page)
    await gw_list_projects()
    assert page.call_args.args[2] == {"id": {"_in": [49]}, "clientId": {"_in": [7]}}


@pytest.mark.parametrize(
    "class_name,method,args",
    [
        (
            "direct",
            "create",
            (49, 81, ReportFindingContent(title="Test", severity="info", description="Test")),
        ),
        ("direct", "update", (49, 81, 1, ReportFindingChanges(title="Changed"))),
        ("reporting", "delete_finding", (49, 81, 1)),
        ("reporting", "attach_library", (49, 81, 1)),
        ("reporting", "create_report", (49, "Test")),
        ("reporting", "update_report", (49, 81, ReportChanges(title="Changed"))),
        ("reporting", "summary", (49, 81, "Summary", "executive_summary")),
        ("reporting", "upload_evidence", (49, 81, "eA==", "test.txt", "Test", "Caption")),
        ("reporting", "attach_evidence", (49, 81, 1, 1)),
        ("reporting", "delete_evidence", (49, 81, 1)),
        ("reporting", "select_templates", (49, 81, ReportTemplateSelection(docx_template_id=1))),
    ],
)
async def test_every_write_path_rejects_a_project_under_wrong_client(
    monkeypatch, class_name, method, args
):
    monkeypatch.setattr(settings(), "allowed_clients", [7])
    client = Ghostwriter()
    calls = AsyncMock(return_value={"project_by_pk": {"id": 49, "clientId": 8}})
    monkeypatch.setattr(client, "execute", calls)
    service = DirectAuthoring(client) if class_name == "direct" else Reporting(client)
    with pytest.raises(DomainError, match="client scope"):
        await getattr(service, method)(*args)
    assert calls.await_count == 1
    assert calls.call_args.args[0] == q.PROJECT  # No mutation or report-content read occurred.
