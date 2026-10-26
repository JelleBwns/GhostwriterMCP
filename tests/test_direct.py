import gzip
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from graphql import build_client_schema, get_introspection_query, parse, validate
from pydantic import SecretStr, ValidationError

from gw_reporting import queries as q
from gw_reporting.config import settings
from gw_reporting.direct import DirectAuthoring, rich_text
from gw_reporting.ghostwriter import Ghostwriter
from gw_reporting.mcp import mcp
from gw_reporting.schemas import (
    DomainError,
    ReportFindingChanges,
    ReportFindingContent,
    Severity,
    digest,
)


@pytest.fixture
def schema():
    data = json.loads(
        gzip.decompress((Path(__file__).parent / "fixtures/upstream-schema.json.gz").read_bytes())
    )
    return build_client_schema(data)


@pytest.fixture
def remote():
    client = AsyncMock(spec=Ghostwriter)
    client.report.return_value = {"id": 81, "projectId": 49}
    client.project.return_value = {"id": 49}
    client.page.return_value = []
    return client


@pytest.fixture
def content():
    return ReportFindingContent(
        title="MCP integration test — safe to delete",
        severity="info",
        description="A test of report authoring. This does not represent a security vulnerability.",
        impact="No security impact; integration testing only.",
        remediation="Remove this test finding after verification.",
        reproduction="Created through the Ghostwriter MCP integration.",
        finding_type_id=7,
    )


@pytest.fixture
def author(remote):
    author = DirectAuthoring(remote)
    author.options = AsyncMock(
        return_value={
            "severities": [{"id": 5, "severity": "Informational"}],
            "finding_types": [{"id": 7, "findingType": "Network"}],
        }
    )
    return author


def test_documents_match_upstream_schema(schema):
    for name in ["PROJECT", "REPORT", "FINDING_TYPES", "DIRECT_INSERT", "DIRECT_UPDATE"]:
        assert not validate(schema, parse(getattr(q, name))), name
    for table, fields in [
        ("reportedFinding", q.DIRECT_FINDING_FIELDS),
        ("findingSeverity", "id severity"),
        ("project", "id codename"),
    ]:
        assert not validate(schema, parse(f"query {{ {table} {{ {fields} }} }}"))


def test_models_reject_invalid_content():
    for data in [
        {"title": " ", "severity": "info", "description": "x"},
        {"title": "x", "severity": "urgent", "description": "x"},
        {"title": "x", "severity": "info", "description": "x", "cvss_score": 11},
        {"title": "x", "severity": "info", "description": "x", "approved": True},
    ]:
        with pytest.raises(ValidationError):
            ReportFindingContent.model_validate(data)
    for data in [
        {},
        {"title": None},
        {"title": " "},
        {"description": None},
        {"finding_type_id": -1},
    ]:
        with pytest.raises(ValidationError):
            ReportFindingChanges.model_validate(data)
    assert ReportFindingChanges(cvss_score=None).model_dump(exclude_unset=True) == {
        "cvss_score": None
    }


def test_plain_text_cannot_inject_html():
    assert (
        rich_text("<script>alert(1)</script>\nnext")
        == "<p>&lt;script&gt;alert(1)&lt;/script&gt;<br>next</p>"
    )
    assert rich_text("") == ""


async def test_create_without_local_services(author, remote, content):
    remote.page.side_effect = [[], [{"id": 3, "position": 4}]]
    remote.execute.return_value = {
        "insert_reportedFinding_one": {
            "id": 1234,
            "reportId": 81,
            "title": content.title,
            "complete": False,
        }
    }
    result = await author.create(49, 81, content)
    assert result["status"] == "created"
    assert result["finding_id"] == 1234
    remote.report.assert_awaited_once_with(49, 81)
    query, variables = remote.execute.call_args.args
    assert query == q.DIRECT_INSERT
    fields = variables["object"]
    assert fields["reportId"] == 81
    assert fields["severityId"] == 5
    assert fields["findingTypeId"] == 7
    assert fields["position"] == 5
    assert fields["complete"] is False
    assert fields["mitigation"] == rich_text(content.remediation)
    assert "cvss_score" not in fields


async def test_repeated_content_reuses_remote_record(author, remote, content):
    fields = await author.fields(49, content.model_dump(), creating=True)
    remote.page.return_value = [{**fields, "id": 1234, "reportId": 81, "complete": True}]
    result = await author.create(49, 81, content)
    assert result["status"] == "already_exists"
    assert result["complete"] is True
    remote.execute.assert_not_awaited()


async def test_same_title_with_different_content_is_not_silently_reused(author, remote, content):
    fields = await author.fields(49, content.model_dump(), creating=True)
    remote.page.side_effect = [[{**fields, "id": 1, "description": "Different content"}], []]
    remote.execute.return_value = {
        "insert_reportedFinding_one": {
            "id": 2,
            "reportId": 81,
            "title": content.title,
            "complete": False,
        }
    }
    assert (await author.create(49, 81, content))["finding_id"] == 2


async def test_creation_denied_for_wrong_report(author, remote, content):
    remote.report.side_effect = DomainError("forbidden", "Report is outside project")
    with pytest.raises(DomainError, match="outside"):
        await author.create(49, 82, content)
    remote.execute.assert_not_awaited()


async def test_type_and_severity_validation(author, remote, content):
    with pytest.raises(DomainError, match="not visible"):
        await author.create(49, 81, content.model_copy(update={"finding_type_id": 999}))
    with pytest.raises(DomainError, match="no severity"):
        await author.create(49, 81, content.model_copy(update={"severity": Severity.critical}))
    author.options.return_value["finding_types"].append({"id": 8, "findingType": "Web"})
    with pytest.raises(DomainError, match="Choose"):
        await author.create(49, 81, content.model_copy(update={"finding_type_id": None}))
    remote.execute.assert_not_awaited()


async def test_single_type_can_be_selected_automatically(author, remote, content):
    fields = await author.fields(
        49, content.model_copy(update={"finding_type_id": None}).model_dump(), True
    )
    assert fields["findingTypeId"] == 7


async def test_update_only_supplied_fields_and_uses_atomic_scope(author, remote):
    current = {
        "id": 1234,
        "reportId": 81,
        "title": "Original",
        "description": "Original body",
        "complete": True,
        "cvss_score": None,
    }
    remote.page.return_value = [current]
    remote.execute.return_value = {
        "update_reportedFinding": {
            "affected_rows": 1,
            "returning": [{"id": 1234, "reportId": 81, "title": "Original", "complete": False}],
        }
    }
    result = await author.update(
        49, 81, 1234, ReportFindingChanges(remediation="Use <safe> settings")
    )
    assert result["status"] == "updated"
    query, variables = remote.execute.call_args.args
    assert query == q.DIRECT_UPDATE
    assert variables["object"] == {
        "mitigation": "<p>Use &lt;safe&gt; settings</p>",
        "complete": False,
    }
    assert variables["where"]["reportId"] == {"_eq": 81}
    assert {"cvss_score": {"_is_null": True}} in variables["where"]["_and"]
    assert {"title": {"_eq": "Original"}} in variables["where"]["_and"]
    author.options.assert_not_awaited()


async def test_update_rejects_cross_report_and_stale_snapshot(author, remote):
    remote.page.return_value = []
    with pytest.raises(DomainError, match="not visible"):
        await author.update(49, 81, 1234, ReportFindingChanges(title="New"))
    remote.page.return_value = [{"id": 1234, "reportId": 81, "title": "Changed"}]
    with pytest.raises(DomainError, match="changed"):
        await author.update(
            49,
            81,
            1234,
            ReportFindingChanges(title="New"),
            expected_content_hash=digest({"title": "Original"}),
        )
    remote.execute.assert_not_awaited()


async def test_update_conflict_does_not_report_success(author, remote):
    remote.page.return_value = [{"id": 1234, "reportId": 81, "title": "Original"}]
    remote.execute.return_value = {"update_reportedFinding": {"affected_rows": 0, "returning": []}}
    with pytest.raises(DomainError, match="changed"):
        await author.update(49, 81, 1234, ReportFindingChanges(title="New"))


@pytest.mark.parametrize("code", ["upstream_unavailable", "upstream_http_error"])
async def test_ambiguous_write_never_retried(author, remote, content, code):
    remote.execute.side_effect = DomainError(code, "timeout")
    with pytest.raises(DomainError, match="may already have been saved"):
        await author.create(49, 81, content)
    assert remote.execute.await_count == 1


async def test_null_insert_result_is_not_success(author, remote, content):
    remote.execute.return_value = {"insert_reportedFinding_one": None}
    with pytest.raises(DomainError, match="did not return"):
        await author.create(49, 81, content)


async def test_options_pagination(remote):
    remote.page.side_effect = [[{"id": i, "severity": str(i)} for i in range(100)], []]
    remote.execute.side_effect = [
        {"findingType": [{"id": i, "findingType": str(i)} for i in range(100)]},
        {"findingType": []},
    ]
    result = await DirectAuthoring(remote).options(49)
    assert len(result["finding_types"]) == 100
    assert remote.execute.call_args.args[1]["offset"] == 100


async def test_scope_checked_before_network():
    client = Ghostwriter()
    with pytest.raises(DomainError, match="scope"):
        await client.project(50)


async def test_missing_credentials_rejected_before_network(monkeypatch):
    monkeypatch.setattr(settings(), "gw_token", SecretStr(""))
    with pytest.raises(DomainError, match="GW_TOKEN"):
        await Ghostwriter().raw("query { __typename }")


async def test_schema_capability_denied_before_write(monkeypatch):
    from graphql import build_schema, graphql_sync

    client = Ghostwriter()
    snapshot = graphql_sync(
        build_schema("type Query {ping:String}"), get_introspection_query()
    ).data
    monkeypatch.setattr(client, "raw", AsyncMock(return_value=snapshot))
    with pytest.raises(DomainError, match="unavailable"):
        await client.execute(q.DIRECT_INSERT, {"object": {}})
    assert client.raw.await_count == 1


async def test_actual_http_schema_preflight_and_create_without_services(
    monkeypatch, schema, content
):
    from graphql import introspection_from_schema

    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["Authorization"] == "Bearer test-token"
        query = body["query"]
        if "__schema" in query:
            data = introspection_from_schema(schema)
        elif "query Project" in query:
            data = {"project_by_pk": {"id": 49, "codename": "Test"}}
        elif "query Report" in query:
            data = {"report_by_pk": {"id": 81, "projectId": 49}}
        elif "findingSeverity(" in query:
            data = {"findingSeverity": [{"id": 5, "severity": "Informational"}]}
        elif "query FindingTypes" in query:
            data = {"findingType": [{"id": 7, "findingType": "Network"}]}
        elif "query Page" in query:
            data = {"reportedFinding": []}
        else:
            assert query == q.DIRECT_INSERT
            data = {
                "insert_reportedFinding_one": {
                    "id": 1234,
                    "reportId": 81,
                    "title": content.title,
                    "complete": False,
                }
            }
        return httpx.Response(200, json={"data": data})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "gw_reporting.ghostwriter.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await DirectAuthoring().create(49, 81, content)
    assert result["finding_id"] == 1234
    writes = [r for r in requests if r["query"].startswith("mutation")]
    assert len(writes) == 1
    assert writes[0]["variables"]["object"]["reportId"] == 81


async def test_transport_does_not_retry_mutation(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "gw_reporting.ghostwriter.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(DomainError):
        await Ghostwriter().raw(q.DIRECT_INSERT, retry=False)
    assert len(calls) == 1


async def test_exact_tool_surface_and_structured_errors():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == {
            "gw_list_projects",
            "gw_get_project",
            "gw_list_reports",
            "gw_get_report",
            "gw_list_findings",
            "gw_search_finding_library",
            "gw_get_finding_options",
            "gw_create_finding",
            "gw_update_finding",
        }
        for tool in tools:
            assert tool.inputSchema and tool.outputSchema
        result = await client.call_tool("gw_get_project", {"project_id": 50})
        assert result.structured_content["ok"] is False
        assert result.structured_content["error"]["code"] == "forbidden"


async def test_stdio_launch_with_only_ghostwriter_settings(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GW_", "DATABASE_", "REDIS_", "S3_", "LLM_", "AGENT_", "REVIEWERS"))
    }
    env.update(
        GW_BASE_URL="https://ghostwriter.example.test",
        GW_TOKEN="test-token",
        ALLOWED_PROJECTS="[49]",
        GW_REPORTING_ENV_FILE=str(tmp_path / "absent.env"),
        GW_ENABLED_TOOLS=json.dumps(
            [
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
        ),
    )
    transport = StdioTransport(
        command=sys.executable, args=["-m", "gw_reporting"], env=env, cwd=str(tmp_path)
    )
    async with Client(transport) as client:
        assert len(await client.list_tools()) == 9


def test_explicit_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "ghostwriter.env"
    env_file.write_text("GW_BASE_URL=https://custom.example.test\nALLOWED_PROJECTS=[77]\n")
    monkeypatch.setenv("GW_REPORTING_ENV_FILE", str(env_file))
    monkeypatch.delenv("GW_BASE_URL")
    monkeypatch.delenv("ALLOWED_PROJECTS")
    settings.cache_clear()
    assert settings().allowed_projects == [77]
    assert settings().gw_base_url == "https://custom.example.test"


@pytest.fixture
def camel_schema():
    from gw_reporting.compat import FIELD_NAMES

    data = json.loads(
        gzip.decompress((Path(__file__).parent / "fixtures/upstream-schema.json.gz").read_bytes())
    )

    def rename(value):
        if isinstance(value, dict):
            return {
                key: FIELD_NAMES.get(item, item)
                if key == "name" and isinstance(item, str)
                else rename(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [rename(item) for item in value]
        return value

    return build_client_schema(rename(data))


def test_live_schema_naming_compatibility(camel_schema):
    from gw_reporting.compat import adapt_operation

    query, variables = adapt_operation(camel_schema, q.REPORT, {"id": 81})
    assert "extra_fields: extraFields" in query
    assert not validate(camel_schema, parse(query))
    assert variables == {"id": 81}
    query, variables = adapt_operation(
        camel_schema,
        q.DIRECT_INSERT,
        {
            "object": {
                "reportId": 81,
                "added_as_blank": True,
                "cvss_score": None,
                "cvss_vector": None,
            }
        },
    )
    assert variables["object"] == {
        "reportId": 81,
        "addedAsBlank": True,
        "cvssScore": None,
        "cvssVector": None,
    }
    query, variables = adapt_operation(
        camel_schema,
        q.DIRECT_UPDATE,
        {
            "where": {"reportId": {"_eq": 81}, "_and": [{"cvss_score": {"_is_null": True}}]},
            "object": {"cvss_score": 7.5},
        },
    )
    assert variables["where"]["_and"] == [{"cvssScore": {"_is_null": True}}]
    assert variables["object"] == {"cvssScore": 7.5}
    assert not validate(camel_schema, parse(query))


def test_legacy_schema_preserves_original_documents(schema):
    from gw_reporting.compat import adapt_operation

    original = {"object": {"cvss_score": None, "added_as_blank": True}}
    query, variables = adapt_operation(schema, q.DIRECT_INSERT, original)
    assert query == q.DIRECT_INSERT
    assert variables == original


async def test_http_write_adapts_deployed_camel_case(monkeypatch, camel_schema, content):
    from graphql import introspection_from_schema

    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        query = body["query"]
        if "__schema" in query:
            data = introspection_from_schema(camel_schema)
        elif "query Project" in query:
            data = {"project_by_pk": {"id": 49}}
        elif "query Report" in query:
            assert "extra_fields: extraFields" in query
            data = {"report_by_pk": {"id": 81, "projectId": 49, "extra_fields": {}}}
        elif "findingSeverity(" in query:
            data = {"findingSeverity": [{"id": 5, "severity": "Informational"}]}
        elif "query FindingTypes" in query:
            data = {"findingType": [{"id": 7, "findingType": "Network"}]}
        elif "query Page" in query:
            if "cvssScore" in query:
                assert "cvss_score: cvssScore" in query
            data = {"reportedFinding": []}
        else:
            fields = body["variables"]["object"]
            assert fields["addedAsBlank"] is True
            assert "cvssScore" not in fields
            assert "added_as_blank" not in fields
            data = {
                "insert_reportedFinding_one": {
                    "id": 1234,
                    "reportId": 81,
                    "title": content.title,
                    "complete": False,
                }
            }
        return httpx.Response(200, json={"data": data})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "gw_reporting.ghostwriter.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert (await DirectAuthoring().create(49, 81, content))["finding_id"] == 1234
    assert len([r for r in requests if r["query"].startswith("mutation")]) == 1
