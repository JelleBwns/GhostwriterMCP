import base64
import json
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from graphql import parse, validate
from pydantic import ValidationError
from schema_support import api_schema

from gw_reporting import queries as q
from gw_reporting.config import settings
from gw_reporting.ghostwriter import Ghostwriter
from gw_reporting.mcp import CONVENIENCE
from gw_reporting.registry import TOOL_METADATA, build_server
from gw_reporting.reporting import Reporting, decode_file
from gw_reporting.schemas import DomainError, ReportChanges, ReportTemplateSelection


@pytest.fixture
def remote():
    client = AsyncMock(spec=Ghostwriter)
    client.report.return_value = {
        "id": 81,
        "projectId": 49,
        "title": "Assessment",
        "complete": False,
        "archived": False,
        "delivered": False,
        "extra_fields": {"executive_summary": "Old", "other": "Preserve"},
        "docxTemplateId": 1,
        "pptxTemplateId": 2,
    }
    client.project.return_value = {"id": 49}
    client.input_fields.return_value = frozenset()
    client.field_nullable.return_value = False
    client.report_field_specs.return_value = {}
    client.page.return_value = []
    return client


@pytest.fixture
def service(remote):
    return Reporting(remote)


def evidence_row():
    return {"id": 9, "report_id": 81, "findingId": None}


def report_response():
    return {
        "update_report": {
            "affected_rows": 1,
            "returning": [{"id": 81, "projectId": 49, "title": "Assessment", "complete": False}],
        }
    }


def test_all_verified_reporting_documents_validate():
    schema = api_schema()
    for name in [
        "PROJECT_CLIENT",
        "REPORT_INSERT",
        "REPORT_UPDATE",
        "SUMMARY_UPDATE",
        "FINDING_DELETE",
        "LIBRARY_ATTACH",
        "EVIDENCE_UPLOAD",
        "EVIDENCE_ATTACH",
        "EVIDENCE_DOWNLOAD",
        "EVIDENCE_DELETE",
        "EVIDENCE_DELETE_ROWS",
        "REPORT_GENERATE",
        "REPORT_EXPORT",
        "REPORT_FIELD_SPECS",
    ]:
        assert not validate(schema, parse(getattr(q, name))), name
    for table, fields in [("evidence", q.EVIDENCE_FIELDS), ("template", q.TEMPLATE_FIELDS)]:
        assert not validate(schema, parse(f"query {{ {table} {{ {fields} }} }}"))


async def test_exactly_23_curated_tools_can_be_exposed():
    assert len(CONVENIENCE) == len(TOOL_METADATA) == 23
    server = build_server(CONVENIENCE, list(CONVENIENCE))
    async with Client(server) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == set(TOOL_METADATA)
        assert not any(t.name.startswith("gw_api_") for t in tools)
        assert not any(
            t.name in {"gw_delete_project", "gw_delete_report", "gw_upload_template"} for t in tools
        )
        assert all(t.inputSchema and t.outputSchema for t in tools)


async def test_allowlist_excludes_unselected_functions_and_aliases():
    selected = ["gw_create_finding", "gw_get_finding_options"]
    server = build_server(CONVENIENCE, selected)
    async with Client(server) as client:
        assert {t.name for t in await client.list_tools()} == set(selected)
        for name in [
            "gw_create_report",
            "gw_delete_evidence",
            "gw_delete_finding",
            "gw_api_mutation_insert_report_one",
        ]:
            with pytest.raises(Exception):
                await client.call_tool(name, {})
    async with Client(build_server(CONVENIENCE, [])) as client:
        assert len(await client.list_tools()) == 23
    for names in [["*"], ["gw_api_query_report"], ["gw_delete_report"], ["typo"]]:
        with pytest.raises(ValueError):
            build_server(CONVENIENCE, names)


def test_metadata_and_template_models_have_no_mutation_escape_hatches():
    for payload in [
        {},
        {"title": None},
        {"title": " "},
        {"projectId": 50},
        {"extra_fields": {"executive_summary": "bad"}},
        {"docxTemplateId": 99},
        {"findings": {"data": [{"title": "nested"}]}},
    ]:
        with pytest.raises(ValidationError):
            ReportChanges.model_validate(payload)
    with pytest.raises(ValidationError):
        ReportTemplateSelection()
    assert ReportTemplateSelection(docx_template_id=None).model_dump(exclude_unset=True) == {
        "docx_template_id": None
    }


async def test_create_report_is_scoped_and_contains_no_nested_inputs(service, remote):
    remote.execute.return_value = {
        "insert_report_one": {"id": 81, "projectId": 49, "title": "Example", "complete": False}
    }
    result = await service.create_report(49, "Example")
    assert result["status"] == "created"
    remote.project.assert_awaited_once_with(49)
    query, variables = remote.execute.call_args.args
    assert query == q.REPORT_INSERT
    fields = variables["object"]
    assert fields["projectId"] == 49
    assert fields["complete"] is False
    assert fields["creation"] and fields["last_update"]
    assert "project" not in fields and "findings" not in fields


async def test_report_metadata_changes_only_selected_fields_with_compare_filter(service, remote):
    remote.execute.return_value = report_response()
    await service.update_report(49, 81, ReportChanges(title="Updated"))
    query, variables = remote.execute.call_args.args
    assert query == q.REPORT_UPDATE
    assert variables["object"] == {"title": "Updated"}
    assert variables["where"]["projectId"] == {"_eq": 49}
    assert {"title": {"_eq": "Assessment"}} in variables["where"]["_and"]


async def test_zero_row_report_update_is_conflict(service, remote):
    remote.execute.return_value = {"update_report": {"affected_rows": 0, "returning": []}}
    with pytest.raises(DomainError, match="changed"):
        await service.update_report(49, 81, ReportChanges(archived=True))


async def test_summary_patches_only_existing_key_and_escapes_text(service, remote):
    remote.execute.return_value = report_response()
    await service.summary(49, 81, "Observed <issue>", "executive_summary")
    query, variables = remote.execute.call_args.args
    assert query == q.SUMMARY_UPDATE
    assert variables["patch"] == {
        "extra_fields": {"executive_summary": "<p>Observed &lt;issue&gt;</p>"}
    }
    assert variables["where"]["extra_fields"] == {"_contains": {"executive_summary": "Old"}}
    assert "other" not in variables["patch"]["extra_fields"]
    remote.execute.reset_mock()
    with pytest.raises(DomainError, match="existing report summary field"):
        await service.summary(49, 81, "Summary", "invented_field")
    remote.execute.assert_not_awaited()


async def test_finding_delete_targets_one_scoped_id(service, remote):
    remote.page.return_value = [{"id": 1336, "reportId": 81}]
    remote.execute.return_value = {
        "delete_reportedFinding": {"affected_rows": 1, "returning": [{"id": 1336}]}
    }
    assert (await service.delete_finding(49, 81, 1336))["status"] == "deleted"
    assert remote.execute.call_args.args == (q.FINDING_DELETE, {"id": 1336, "report": 81})


async def test_library_attachment_verifies_destination_report(service, remote):
    remote.execute.return_value = {"attachFinding": {"id": 1337}}
    remote.page.return_value = [{"id": 1337, "reportId": 81, "complete": False}]
    assert (await service.attach_library(49, 81, 4))["finding_id"] == 1337
    assert remote.execute.call_args.args[1] == {"finding": 4, "report": 81}


@pytest.mark.parametrize(
    "method,args",
    [
        ("delete_finding", (49, 81, 1)),
        ("attach_library", (49, 81, 1)),
        ("upload_evidence", (49, 81, "eA==", "proof.txt", "Proof", "Caption")),
        ("attach_evidence", (49, 81, 9, 1)),
        ("download_evidence", (49, 81, 9)),
        ("delete_evidence", (49, 81, 9)),
        ("generate", (49, 81)),
        ("get_export", (49, 81)),
        ("update_report", (49, 81, ReportChanges(title="Changed"))),
    ],
)
async def test_report_denial_prevents_operations(service, remote, method, args):
    remote.report.side_effect = DomainError("forbidden", "Wrong project/report")
    with pytest.raises(DomainError, match="Wrong"):
        await getattr(service, method)(*args)
    remote.execute.assert_not_awaited()


async def test_evidence_upload_preserves_bytes_and_never_uses_paths(service, remote):
    body = base64.b64encode(b"Original evidence bytes").decode()
    remote.execute.return_value = {"uploadEvidence": {"id": 9}}
    result = await service.upload_evidence(49, 81, body, "proof.txt", "Proof", "Caption")
    assert result["size"] == len(b"Original evidence bytes")
    assert remote.execute.call_args.args[1]["body"] == body
    for filename in ["/etc/passwd", "../proof.txt", "https://example.org/a", "a\\b.txt", ".."]:
        remote.execute.reset_mock()
        with pytest.raises(DomainError, match="basename"):
            await service.upload_evidence(49, 81, body, filename, "Proof", "Caption")
        remote.execute.assert_not_awaited()


def test_base64_limits_and_validation(monkeypatch):
    for body in ["", "bad!", "eA==\n"]:
        with pytest.raises(DomainError):
            decode_file(body)
    monkeypatch.setattr(settings(), "gw_max_file_bytes", 2)
    with pytest.raises(DomainError, match="exceeds"):
        decode_file(base64.b64encode(b"large").decode())


async def test_evidence_attachment_requires_same_report_for_both_records(service, remote):
    remote.page.side_effect = [[evidence_row()], [{"id": 1336, "reportId": 82}]]
    with pytest.raises(DomainError, match="Finding is not visible"):
        await service.attach_evidence(49, 81, 9, 1336)
    remote.execute.assert_not_awaited()
    remote.page.side_effect = [[evidence_row()], [{"id": 1336, "reportId": 81}]]
    remote.execute.return_value = {
        "update_evidence": {
            "affected_rows": 1,
            "returning": [{"id": 9, "report_id": 81, "findingId": 1336}],
        }
    }
    assert (await service.attach_evidence(49, 81, 9, 1336))["status"] == "attached"
    where = remote.execute.call_args.args[1]["where"]
    assert where["report_id"] == {"_eq": 81}
    assert where["findingId"] == {"_is_null": True}


async def test_evidence_download_returns_api_data_without_fetching_url(service, remote):
    remote.page.return_value = [evidence_row()]
    remote.execute.return_value = {
        "downloadEvidence": {
            "evidenceId": 9,
            "filename": "proof.txt",
            "friendlyName": "Proof",
            "downloadUrl": "http://never-fetch.invalid/private",
            "fileBase64": base64.b64encode(b"evidence").decode(),
        }
    }
    result = await service.download_evidence(49, 81, 9)
    assert base64.b64decode(result["file_base64"]) == b"evidence"
    assert "downloadUrl" not in result
    assert remote.execute.await_count == 1


async def test_evidence_delete_uses_action_and_verifies_absence(service, remote):
    remote.page.side_effect = [[evidence_row()], []]
    remote.execute.return_value = {"deleteEvidence": {"result": "success"}}
    assert (await service.delete_evidence(49, 81, 9))["status"] == "deleted"
    assert remote.execute.call_args.args == (q.EVIDENCE_DELETE, {"id": 9})
    remote.page.side_effect = [[evidence_row()], [{"id": 9}]]
    with pytest.raises(DomainError, match="still exists"):
        await service.delete_evidence(49, 81, 9)


async def test_templates_are_filtered_to_global_or_project_client(service, remote):
    remote.execute.return_value = {"project_by_pk": {"id": 49, "clientId": 7}}
    await service.list_templates(49)
    where = remote.page.call_args.args[2]
    assert where == {"_or": [{"clientId": {"_is_null": True}}, {"clientId": {"_eq": 7}}]}


async def test_selecting_template_checks_type_and_preserves_other_slot(service, remote):
    remote.execute.side_effect = [{"project_by_pk": {"id": 49, "clientId": 7}}, report_response()]
    remote.page.return_value = [
        {
            "id": 3,
            "clientId": 7,
            "document": "templates/a.docx",
            "reporting_doctype": {"docType": "DOCX"},
        }
    ]
    await service.select_templates(49, 81, ReportTemplateSelection(docx_template_id=3))
    assert remote.execute.call_args.args[1]["object"] == {"docxTemplateId": 3, "complete": False}
    remote.execute.reset_mock(side_effect=True)
    remote.execute.return_value = {"project_by_pk": {"id": 49, "clientId": 7}}
    remote.page.return_value = [
        {"id": 4, "document": "templates/a.pptx", "reporting_doctype": {"docType": "PPTX"}}
    ]
    with pytest.raises(DomainError, match="DOCX"):
        await service.select_templates(49, 81, ReportTemplateSelection(docx_template_id=4))
    assert remote.execute.await_count == 1


async def test_exports_are_json_not_fake_office_documents(service, remote):
    payload = base64.b64encode(json.dumps({"findings": [{"id": 1336}]}).encode()).decode()
    remote.execute.return_value = {
        "generateReport": {
            "reportData": payload,
            "docxUrl": "/ui/docx",
            "xlsxUrl": "/ui/xlsx",
            "pptxUrl": "/ui/pptx",
        }
    }
    result = await service.generate(49, 81)
    assert result["office_generation_supported"] is False
    assert result["ui_urls"]["docxUrl"] == "/ui/docx"
    assert (await service.get_export(49, 81))["report_data"]["findings"][0]["id"] == 1336
    remote.execute.reset_mock()
    for kind in ["docx", "pptx", "xlsx"]:
        with pytest.raises(DomainError, match="does not render"):
            await service.generate(49, 81, kind)
    remote.execute.assert_not_awaited()


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
async def test_malformed_export_never_reports_success(service, remote, body):
    remote.execute.return_value = {
        "generateReport": {"reportData": base64.b64encode(body).decode()}
    }
    with pytest.raises(DomainError):
        await service.get_export(49, 81)


async def test_writes_are_not_automatically_retried(service, remote):
    remote.execute.side_effect = DomainError("upstream_unavailable", "timeout")
    with pytest.raises(DomainError, match="Inspect Ghostwriter"):
        await service.create_report(49, "Example")
    assert remote.execute.await_count == 1


async def test_configured_summary_field_cannot_be_overridden(service, remote, monkeypatch):
    monkeypatch.setattr(settings(), "gw_summary_field", "executive_summary")
    with pytest.raises(DomainError, match="cannot override"):
        await service.summary(49, 81, "Summary", "other")
    remote.execute.assert_not_awaited()


async def test_template_label_conflict_is_not_overridden_by_filename(service, remote):
    remote.execute.return_value = {"project_by_pk": {"id": 49, "clientId": 7}}
    remote.page.return_value = [
        {"id": 4, "document": "misleading.docx", "reporting_doctype": {"docType": "PPTX"}}
    ]
    with pytest.raises(DomainError, match="DOCX"):
        await service.select_templates(49, 81, ReportTemplateSelection(docx_template_id=4))
    assert remote.execute.await_count == 1


def test_summary_patch_compatibility_uses_schema_aware_variable_mapping():
    import gzip
    from pathlib import Path

    from graphql import build_client_schema

    from gw_reporting.compat import adapt_operation

    raw = (Path(__file__).parent / "fixtures/upstream-schema.json.gz").read_bytes()
    data = json.loads(gzip.decompress(raw))

    def rename(value):
        if isinstance(value, dict):
            return {
                k: ("extraFields" if k == "name" and v == "extra_fields" else rename(v))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [rename(v) for v in value]
        return value

    schema = build_client_schema(rename(data))
    query, variables = adapt_operation(
        schema,
        q.SUMMARY_UPDATE,
        {"where": {"id": {"_eq": 81}}, "patch": {"extra_fields": {"executive_summary": "Updated"}}},
    )
    assert not validate(schema, parse(query))
    assert variables["patch"] == {"extraFields": {"executive_summary": "Updated"}}


async def test_report_creation_adds_only_supported_version_specific_defaults(service, remote):
    remote.execute.return_value = {
        "insert_report_one": {"id": 81, "projectId": 49, "title": "Example", "complete": False}
    }
    remote.input_fields.return_value = frozenset({"include_bloodhound_data"})
    await service.create_report(49, "Example")
    assert remote.execute.call_args.args[1]["object"]["include_bloodhound_data"] is False
    remote.input_fields.return_value = frozenset()
    await service.create_report(49, "Example")
    assert "include_bloodhound_data" not in remote.execute.call_args.args[1]["object"]


async def test_newer_evidence_schema_uses_finding_or_report_not_both(service, remote):
    remote.field_nullable.return_value = True
    remote.page.side_effect = [[evidence_row()], [{"id": 1336, "reportId": 81}]]
    remote.execute.return_value = {
        "update_evidence": {
            "affected_rows": 1,
            "returning": [
                {"id": 9, "report_id": None, "findingId": 1336, "finding": {"reportId": 81}}
            ],
        }
    }
    assert (await service.attach_evidence(49, 81, 9, 1336))["status"] == "attached"
    assert remote.execute.call_args.args[1]["object"] == {"findingId": 1336, "report_id": None}


async def test_finding_owned_evidence_is_scoped_through_parent_finding(service, remote):
    remote.page.return_value = [
        {"id": 9, "report_id": None, "findingId": 1336, "finding": {"reportId": 81}}
    ]
    assert (await service.evidence(49, 81, 9))["id"] == 9
    filters = remote.page.call_args.args[2]
    assert {"report_id": {"_is_null": True}, "finding": {"reportId": {"_eq": 81}}} in filters["_or"]
    remote.page.return_value = [
        {"id": 9, "report_id": None, "findingId": 1336, "finding": {"reportId": 82}}
    ]
    with pytest.raises(DomainError, match="not visible"):
        await service.evidence(49, 81, 9)


async def test_summary_can_initialize_a_registered_but_unpopulated_field(service, remote):
    remote.report.return_value["extra_fields"] = {}
    remote.report_field_specs.return_value = {
        "management_summary": {"type": "rich_text", "default": ""}
    }
    remote.execute.return_value = report_response()
    await service.summary(49, 81, "Summary", "management_summary")
    query, variables = remote.execute.call_args.args
    assert variables["patch"] == {"extra_fields": {"management_summary": "<p>Summary</p>"}}
    assert variables["where"]["_not"] == {"extra_fields": {"_has_key": "management_summary"}}
    assert query == q.SUMMARY_UPDATE


async def test_report_context_includes_field_names_without_admin_defaults(service, remote):
    remote.report_field_specs.return_value = {
        "summary": {
            "displayName": "Management Summary",
            "type": "rich_text",
            "default": "Private default text",
        }
    }
    result = await service.get_report(49, 81)
    assert result["extra_field_specs"] == {
        "summary": {"display_name": "Management Summary", "type": "rich_text"}
    }
    assert "Private default text" not in str(result)


async def test_evidence_delete_fallback_is_scoped_and_reports_file_uncertainty(service, remote):
    remote.page.side_effect = [[evidence_row()], []]
    remote.execute.side_effect = [
        DomainError("unsupported_operation", "Action absent"),
        {"delete_evidence": {"affected_rows": 1, "returning": [{"id": 9}]}},
    ]
    result = await service.delete_evidence(49, 81, 9)
    assert result["status"] == "deleted"
    assert result["deletion_mechanism"] == "delete_evidence"
    assert result["storage_cleanup"] == "not_verified"
    query, variables = remote.execute.call_args.args
    assert query == q.EVIDENCE_DELETE_ROWS
    assert variables["where"]["id"] == {"_eq": 9}
    assert {"report_id": {"_eq": 81}} in variables["where"]["_or"]


@pytest.mark.parametrize("code", ["graphql_error", "upstream_unavailable", "upstream_http_error"])
async def test_evidence_delete_does_not_fallback_on_denied_or_uncertain_action(
    service, remote, code
):
    remote.page.return_value = [evidence_row()]
    remote.execute.side_effect = DomainError(code, "denied or uncertain")
    with pytest.raises(DomainError):
        await service.delete_evidence(49, 81, 9)
    assert remote.execute.await_count == 1


async def test_uninitialized_numeric_field_is_not_treated_as_summary(service, remote):
    remote.report.return_value["extra_fields"] = {}
    remote.report_field_specs.return_value = {"numeric": {"type": "integer", "default": None}}
    with pytest.raises(DomainError, match="not a narrative"):
        await service.summary(49, 81, "Summary", "numeric")
    remote.execute.assert_not_awaited()
