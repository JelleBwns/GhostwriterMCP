"""Scoped, stateless reporting operations against verified Ghostwriter GraphQL APIs."""

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from . import queries as q
from .config import settings
from .direct import rich_text
from .ghostwriter import Ghostwriter
from .schemas import DomainError, ReportChanges, ReportTemplateSelection


def compare(value: Any) -> dict:
    return {"_is_null": True} if value is None else {"_eq": value}


def decode_file(value: str, code: str = "invalid_file") -> bytes:
    maximum = settings().gw_max_file_bytes
    if not isinstance(value, str) or not value or len(value) > ((maximum + 2) // 3) * 4:
        raise DomainError(code, "Base64 content is empty or exceeds GW_MAX_FILE_BYTES")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise DomainError(code, "Content must be valid single-line base64") from None
    if not data or len(data) > maximum:
        raise DomainError(code, "Decoded file is empty or exceeds GW_MAX_FILE_BYTES")
    return data


def evidence_scope(report_id: int) -> dict:
    return {
        "_or": [
            {"report_id": {"_eq": report_id}},
            {"report_id": {"_is_null": True}, "finding": {"reportId": {"_eq": report_id}}},
        ]
    }


def evidence_report(row: dict) -> Any:
    return (
        row.get("report_id")
        if row.get("report_id") is not None
        else (row.get("finding") or {}).get("reportId")
    )


class Reporting:
    def __init__(self, client: Ghostwriter | None = None):
        self.client = client or Ghostwriter()

    async def get_report(self, project_id: int, report_id: int) -> dict:
        report = await self.client.report(project_id, report_id)
        try:
            fields = await self.client.report_field_specs()
            report = {
                **report,
                "extra_field_specs": {
                    name: {"display_name": spec.get("displayName", name), "type": spec.get("type")}
                    for name, spec in fields.items()
                    if isinstance(spec, dict)
                },
            }
        except DomainError as exc:
            report = {**report, "field_spec_warning": exc.code}
        return report

    async def write(self, query: str, variables: dict) -> dict:
        try:
            return await self.client.execute(query, variables)
        except DomainError as exc:
            if exc.code in {"upstream_unavailable", "upstream_http_error"}:
                raise DomainError(
                    "write_outcome_unknown",
                    "Inspect Ghostwriter before retrying; the write response was not received",
                ) from None
            raise

    async def finding(self, project_id: int, report_id: int, finding_id: int) -> dict:
        await self.client.report(project_id, report_id)
        rows = await self.client.page(
            "reportedFinding",
            q.DIRECT_FINDING_FIELDS,
            {"id": {"_eq": finding_id}, "reportId": {"_eq": report_id}},
            limit=1,
        )
        if not rows or int(rows[0].get("reportId", -1)) != report_id:
            raise DomainError("forbidden", "Finding is not visible in the requested report")
        return rows[0]

    async def evidence(self, project_id: int, report_id: int, evidence_id: int) -> dict:
        await self.client.report(project_id, report_id)
        rows = await self.client.page(
            "evidence",
            q.EVIDENCE_FIELDS,
            {"id": {"_eq": evidence_id}, **evidence_scope(report_id)},
            limit=1,
        )
        if (
            not rows
            or int(evidence_report(rows[0]) if evidence_report(rows[0]) is not None else -1)
            != report_id
        ):
            raise DomainError("forbidden", "Evidence is not visible in the requested report")
        return rows[0]

    async def delete_finding(self, project_id: int, report_id: int, finding_id: int) -> dict:
        await self.finding(project_id, report_id, finding_id)
        result = (await self.write(q.FINDING_DELETE, {"id": finding_id, "report": report_id})).get(
            "delete_reportedFinding"
        ) or {}
        if result.get("affected_rows") != 1:
            raise DomainError("remote_conflict", "Finding changed scope or deletion was denied")
        return {"status": "deleted", "finding_id": finding_id, "report_id": report_id}

    async def attach_library(
        self, project_id: int, report_id: int, library_finding_id: int
    ) -> dict:
        await self.client.report(project_id, report_id)
        result = (
            await self.write(q.LIBRARY_ATTACH, {"finding": library_finding_id, "report": report_id})
        ).get("attachFinding")
        if not result or not result.get("id"):
            raise DomainError("write_denied", "Ghostwriter returned no attached finding")
        try:
            row = await self.finding(project_id, report_id, int(result["id"]))
        except DomainError:
            raise DomainError(
                "write_outcome_unknown",
                "Attachment returned an ID but report membership could not be verified; inspect Ghostwriter before retrying",
            ) from None
        return {
            "status": "attached",
            "finding_id": row["id"],
            "report_id": report_id,
            "complete": row.get("complete"),
        }

    async def create_report(self, project_id: int, title: str) -> dict:
        await self.client.project(project_id)
        title = title.strip()
        if not title or len(title) > 512:
            raise DomainError("invalid_arguments", "Report title must contain 1–512 characters")
        today = datetime.now(timezone.utc).date().isoformat()
        fields = {
            "projectId": project_id,
            "title": title,
            "creation": today,
            "last_update": today,
            "complete": False,
            "archived": False,
            "delivered": False,
            "extra_fields": {},
        }
        available = await self.client.input_fields("report_insert_input")
        if "include_bloodhound_data" in available or "includeBloodhoundData" in available:
            fields["include_bloodhound_data"] = False
        row = (await self.write(q.REPORT_INSERT, {"object": fields})).get("insert_report_one")
        if not row or int(row.get("projectId", -1)) != project_id:
            raise DomainError(
                "write_outcome_unknown",
                "Ghostwriter did not return a report in the requested project; inspect before retrying",
            )
        return {"status": "created", "report": row}

    def report_result(self, result: dict, project_id: int, report_id: int) -> dict:
        result = result.get("update_report") or {}
        rows = result.get("returning") or []
        if result.get("affected_rows") != 1 or len(rows) != 1:
            raise DomainError("remote_conflict", "Report changed or update permission was denied")
        row = rows[0]
        if int(row.get("id", -1)) != report_id or int(row.get("projectId", -1)) != project_id:
            raise DomainError(
                "write_outcome_unknown", "Unexpected report returned; inspect Ghostwriter"
            )
        return {"status": "updated", "report": row}

    async def update_report(self, project_id: int, report_id: int, changes: ReportChanges) -> dict:
        current = await self.client.report(project_id, report_id)
        fields = changes.model_dump(exclude_unset=True)
        where = {
            "id": {"_eq": report_id},
            "projectId": {"_eq": project_id},
            "_and": [{key: compare(current.get(key))} for key in fields],
        }
        return self.report_result(
            await self.write(q.REPORT_UPDATE, {"where": where, "object": fields}),
            project_id,
            report_id,
        )

    async def summary(
        self, project_id: int, report_id: int, summary: str, field_name: str | None = None
    ) -> dict:
        report = await self.client.report(project_id, report_id)
        configured = settings().gw_summary_field
        if configured and field_name and field_name != configured:
            raise DomainError(
                "forbidden", "field_name cannot override the configured GW_SUMMARY_FIELD"
            )
        field = configured or field_name
        extra = report.get("extra_fields") or {}
        if not isinstance(extra, dict):
            raise DomainError("invalid_response", "Report extra fields are not an object")
        if not field:
            raise DomainError(
                "configuration_required",
                "Select an existing report summary field using field_name or GW_SUMMARY_FIELD",
            )
        missing = field not in extra
        old = extra.get(field)
        if missing:
            specifications = await self.client.report_field_specs()
            specification = specifications.get(field) if isinstance(specifications, dict) else None
            if not isinstance(specification, dict):
                raise DomainError(
                    "configuration_required",
                    "Select an existing report summary field using field_name or GW_SUMMARY_FIELD",
                )
            if specification.get("type") not in {"rich_text", "text"}:
                raise DomainError(
                    "unsupported_operation", "The registered field is not a narrative text field"
                )
            old = specification.get("default")
        if not isinstance(old, (str, type(None))):
            raise DomainError(
                "unsupported_operation",
                "The selected summary field is not a string-backed narrative field",
            )
        if not summary.strip() or len(summary) > 100_000:
            raise DomainError("invalid_arguments", "Summary must contain 1–100000 characters")
        where = {"id": {"_eq": report_id}, "projectId": {"_eq": project_id}}
        if missing:
            where["_not"] = {"extra_fields": {"_has_key": field}}
        else:
            where["extra_fields"] = {"_contains": {field: extra[field]}}
        result = await self.write(
            q.SUMMARY_UPDATE,
            {"where": where, "patch": {"extra_fields": {field: rich_text(summary)}}},
        )
        return self.report_result(result, project_id, report_id)

    async def list_evidence(
        self, project_id: int, report_id: int, offset: int = 0, limit: int = 100
    ) -> list[dict]:
        await self.client.report(project_id, report_id)
        return await self.client.page(
            "evidence", q.EVIDENCE_FIELDS, evidence_scope(report_id), offset, limit
        )

    async def upload_evidence(
        self,
        project_id: int,
        report_id: int,
        file_base64: str,
        filename: str,
        friendly_name: str,
        caption: str,
        description: str = "",
    ) -> dict:
        await self.client.report(project_id, report_id)
        if (
            not filename
            or len(filename) > 255
            or filename in {".", ".."}
            or any(ord(c) < 32 for c in filename)
            or any(c in filename for c in ("/", "\\", "\x00"))
        ):
            raise DomainError("invalid_arguments", "filename must be a basename, not a path or URL")
        if not friendly_name.strip() or len(friendly_name) > 255:
            raise DomainError("invalid_arguments", "friendly_name must contain 1–255 characters")
        if len(caption) > 100_000 or len(description) > 100_000:
            raise DomainError("invalid_arguments", "Evidence text is too long")
        data = decode_file(file_base64)
        result = (
            await self.write(
                q.EVIDENCE_UPLOAD,
                {
                    "body": file_base64,
                    "filename": filename,
                    "name": friendly_name.strip(),
                    "caption": rich_text(caption),
                    "description": rich_text(description),
                    "report": report_id,
                },
            )
        ).get("uploadEvidence")
        if not result or not result.get("id"):
            raise DomainError("write_denied", "Ghostwriter returned no uploaded evidence ID")
        return {
            "status": "uploaded",
            "evidence_id": result["id"],
            "report_id": report_id,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    async def attach_evidence(
        self, project_id: int, report_id: int, evidence_id: int, finding_id: int
    ) -> dict:
        row = await self.evidence(project_id, report_id, evidence_id)
        await self.finding(project_id, report_id, finding_id)
        where = {
            "id": {"_eq": evidence_id},
            **evidence_scope(report_id),
            "report_id": compare(row.get("report_id")),
            "findingId": compare(row.get("findingId")),
        }
        fields = {"findingId": finding_id}
        if await self.client.field_nullable("evidence", "report_id"):
            # Newer Ghostwriter enforces finding XOR direct report ownership.
            fields["report_id"] = None
        response = (await self.write(q.EVIDENCE_ATTACH, {"where": where, "object": fields})).get(
            "update_evidence"
        ) or {}
        rows = response.get("returning") or []
        if response.get("affected_rows") != 1 or len(rows) != 1:
            raise DomainError(
                "remote_conflict", "Evidence changed or attachment permission was denied"
            )
        linked = rows[0]
        if (
            int(evidence_report(linked) if evidence_report(linked) is not None else -1) != report_id
            or int(linked.get("findingId", -1)) != finding_id
        ):
            raise DomainError("write_outcome_unknown", "Attachment result could not be verified")
        return {
            "status": "attached",
            "evidence_id": evidence_id,
            "finding_id": finding_id,
            "report_id": report_id,
        }

    async def download_evidence(self, project_id: int, report_id: int, evidence_id: int) -> dict:
        await self.evidence(project_id, report_id, evidence_id)
        row = (await self.client.execute(q.EVIDENCE_DOWNLOAD, {"id": evidence_id})).get(
            "downloadEvidence"
        )
        if not row or int(row.get("evidenceId", -1)) != evidence_id:
            raise DomainError("invalid_response", "Ghostwriter returned no matching evidence")
        data = decode_file(row.get("fileBase64"), "invalid_response")
        return {
            "evidence_id": evidence_id,
            "filename": row["filename"],
            "friendly_name": row["friendlyName"],
            "file_base64": row["fileBase64"],
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }

    async def delete_evidence(self, project_id: int, report_id: int, evidence_id: int) -> dict:
        await self.evidence(project_id, report_id, evidence_id)
        mechanism = "deleteEvidence"
        try:
            response = (await self.write(q.EVIDENCE_DELETE, {"id": evidence_id})).get(
                "deleteEvidence"
            )
            if not response or not response.get("result"):
                raise DomainError(
                    "write_denied", "Ghostwriter returned no evidence deletion result"
                )
        except DomainError as exc:
            # Only a schema-unavailable Action permits this alternative. Never retry
            # or bypass an Action authorization error or an uncertain write.
            if exc.code != "unsupported_operation":
                raise
            mechanism = "delete_evidence"
            where = {"id": {"_eq": evidence_id}, **evidence_scope(report_id)}
            result = (await self.write(q.EVIDENCE_DELETE_ROWS, {"where": where})).get(
                "delete_evidence"
            ) or {}
            if result.get("affected_rows") != 1:
                raise DomainError(
                    "remote_conflict", "Evidence changed scope or deletion was denied"
                )
        try:
            remaining = await self.client.page(
                "evidence", "id", {"id": {"_eq": evidence_id}}, limit=1
            )
        except DomainError:
            raise DomainError(
                "write_outcome_unknown",
                "Deletion response received but absence could not be verified",
            ) from None
        if remaining:
            raise DomainError("write_denied", "Evidence still exists after deletion")
        result = {
            "status": "deleted",
            "evidence_id": evidence_id,
            "report_id": report_id,
            "deletion_mechanism": mechanism,
        }
        if mechanism == "delete_evidence":
            result["storage_cleanup"] = "not_verified"
        return result

    async def template_scope(self, project_id: int) -> dict:
        await self.client.project(project_id)
        project = (await self.client.execute(q.PROJECT_CLIENT, {"id": project_id})).get(
            "project_by_pk"
        )
        if not project:
            raise DomainError("forbidden", "Project is not visible")
        scopes = [{"clientId": {"_is_null": True}}]
        if project.get("clientId") is not None:
            scopes.append({"clientId": {"_eq": project["clientId"]}})
        return {"_or": scopes}

    async def list_templates(
        self, project_id: int, offset: int = 0, limit: int = 100
    ) -> list[dict]:
        return await self.client.page(
            "template", q.TEMPLATE_FIELDS, await self.template_scope(project_id), offset, limit
        )

    async def select_templates(
        self, project_id: int, report_id: int, selection: ReportTemplateSelection
    ) -> dict:
        report = await self.client.report(project_id, report_id)
        scope = await self.template_scope(project_id)
        fields = {"complete": False}
        for local, template_id in selection.model_dump(exclude_unset=True).items():
            kind = "docx" if local == "docx_template_id" else "pptx"
            if template_id is not None:
                rows = await self.client.page(
                    "template",
                    q.TEMPLATE_FIELDS,
                    {"_and": [scope, {"id": {"_eq": template_id}}]},
                    limit=1,
                )
                if not rows:
                    raise DomainError(
                        "forbidden", "Template is not available to this project/client"
                    )
                row = rows[0]
                label = (row.get("reporting_doctype") or {}).get("docType", "").casefold()
                extension = PurePosixPath(row.get("document") or "").suffix.casefold()
                declared = None
                if "pptx" in label or "powerpoint" in label:
                    declared = "pptx"
                elif "docx" in label or "word" in label:
                    declared = "docx"
                type_matches = declared == kind if declared else extension == f".{kind}"
                if "project" in label or not type_matches:
                    raise DomainError(
                        "invalid_template",
                        f"Template is not verified as a report {kind.upper()} template",
                    )
            fields[f"{kind}TemplateId"] = template_id
        where = {
            "id": {"_eq": report_id},
            "projectId": {"_eq": project_id},
            "_and": [{key: compare(report.get(key))} for key in fields if key != "complete"],
        }
        return self.report_result(
            await self.write(q.REPORT_UPDATE, {"where": where, "object": fields}),
            project_id,
            report_id,
        )

    async def generate(self, project_id: int, report_id: int, document_type: str = "json") -> dict:
        if document_type != "json":
            raise DomainError(
                "unsupported_operation",
                "The verified API exports report-data JSON and UI URLs; it does not render/download Office documents with bearer authentication",
            )
        await self.client.report(project_id, report_id)
        row = (await self.client.execute(q.REPORT_GENERATE, {"id": report_id})).get(
            "generateReport"
        )
        if not row:
            raise DomainError("invalid_response", "Ghostwriter returned no report export")
        data = decode_file(row.get("reportData"), "invalid_response")
        try:
            parsed = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise DomainError("invalid_response", "Report data is not UTF-8 JSON") from None
        if not isinstance(parsed, dict):
            raise DomainError("invalid_response", "Report data must be a JSON object")
        return {
            "report_id": report_id,
            "format": "json",
            "report_data_base64": row["reportData"],
            "size": len(data),
            "office_generation_supported": False,
            "ui_urls": {key: row.get(key) for key in ("docxUrl", "xlsxUrl", "pptxUrl")},
        }

    async def get_export(self, project_id: int, report_id: int) -> dict:
        await self.client.report(project_id, report_id)
        row = (await self.client.execute(q.REPORT_EXPORT, {"id": report_id})).get("generateReport")
        if not row:
            raise DomainError("invalid_response", "Ghostwriter returned no report-data export")
        try:
            data = json.loads(decode_file(row.get("reportData"), "invalid_response"))
        except (ValueError, UnicodeDecodeError):
            raise DomainError("invalid_response", "Report data is not UTF-8 JSON") from None
        if not isinstance(data, dict):
            raise DomainError("invalid_response", "Report data must be a JSON object")
        return {"report_id": report_id, "format": "json", "report_data": data}
