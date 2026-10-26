"""Direct agent authoring: only the external Ghostwriter API is required.

No AI provider, approval database, background queue or evidence store is invoked here.
The calling client's tool permissions authorize these writes. Records remain incomplete
in Ghostwriter for subsequent report QA.
"""

from html import escape
from typing import Any

from . import queries as q
from .config import settings
from .ghostwriter import Ghostwriter
from .schemas import (
    DomainError,
    ReportFindingChanges,
    ReportFindingContent,
    Severity,
    digest,
)


def rich_text(value: str) -> str:
    """Render untrusted plain text as inert paragraphs, preserving line breaks."""
    if not value:
        return ""
    return "<p>" + escape(value).replace("\n", "<br>") + "</p>"


class DirectAuthoring:
    def __init__(self, client: Ghostwriter | None = None) -> None:
        self.client = client or Ghostwriter()

    async def options(self, project_id: int) -> dict[str, Any]:
        await self.client.project(project_id)
        severities = []
        while True:
            page = await self.client.page("findingSeverity", "id severity", {}, len(severities))
            severities.extend(page)
            if len(page) < 100:
                break
        types = []
        while True:
            page = (await self.client.execute(q.FINDING_TYPES, {"offset": len(types)}))[
                "findingType"
            ]
            types.extend(page)
            if len(page) < 100:
                break
        return {
            "severities": severities,
            "finding_types": types,
            "configured_finding_type_id": settings().finding_type_id,
        }

    async def fields(self, project_id: int, content: dict[str, Any], creating: bool) -> dict:
        fields: dict[str, Any] = {"complete": False}
        if "severity" in content or "finding_type_id" in content:
            options = await self.options(project_id)
            if "severity" in content:
                severity = Severity(content["severity"])
                labels = {severity.value}
                if severity == Severity.info:
                    labels.update({"informational", "information"})
                match = next(
                    (s for s in options["severities"] if s["severity"].strip().lower() in labels),
                    None,
                )
                if not match:
                    raise DomainError(
                        "configuration_required",
                        f"Ghostwriter has no severity matching {severity.value}; inspect gw_get_finding_options",
                    )
                fields["severityId"] = match["id"]
            if creating or "finding_type_id" in content:
                type_id = content.get("finding_type_id") or settings().finding_type_id
                if type_id is None and len(options["finding_types"]) == 1:
                    type_id = int(options["finding_types"][0]["id"])
                if type_id is None:
                    raise DomainError(
                        "finding_type_required",
                        "Choose finding_type_id from gw_get_finding_options or configure FINDING_TYPE_ID",
                    )
                if not any(int(t["id"]) == type_id for t in options["finding_types"]):
                    raise DomainError(
                        "invalid_finding_type",
                        "Selected finding type is not visible to this Ghostwriter identity",
                    )
                fields["findingTypeId"] = type_id
        for key, remote in {
            "description": "description",
            "impact": "impact",
            "remediation": "mitigation",
            "reproduction": "replication_steps",
        }.items():
            if key in content:
                fields[remote] = rich_text(content[key])
        if "title" in content:
            fields["title"] = content["title"]
        for key, remote in {
            "affected_entities": "affectedEntities",
            "references": "references",
        }.items():
            if key in content:
                fields[remote] = rich_text("\n".join(content[key]))
        for key in ("cvss_score", "cvss_vector"):
            if key in content:
                fields[key] = content[key]
        return fields

    async def create(self, project_id: int, report_id: int, finding: ReportFindingContent) -> dict:
        await self.client.report(project_id, report_id)
        fields = await self.fields(project_id, finding.model_dump(exclude_none=True), creating=True)
        # Repeated identical submissions reuse the existing finding. This check is not
        # a cross-client atomic uniqueness guarantee; upstream provides none.
        offset = 0
        while True:
            candidates = await self.client.page(
                "reportedFinding",
                q.DIRECT_FINDING_FIELDS,
                {"reportId": {"_eq": report_id}, "title": {"_eq": finding.title}},
                offset,
            )
            for candidate in candidates:
                if all(candidate.get(k) == v for k, v in fields.items() if k != "complete"):
                    return {
                        "status": "already_exists",
                        "finding_id": candidate["id"],
                        "report_id": report_id,
                        "project_id": project_id,
                        "complete": candidate["complete"],
                        "content_hash": digest(candidate),
                    }
            if len(candidates) < 100:
                break
            offset += len(candidates)
        # Position is presentation order, not a remotely assigned identifier.
        positions = []
        while True:
            page = await self.client.page(
                "reportedFinding", "id position", {"reportId": {"_eq": report_id}}, len(positions)
            )
            positions.extend(page)
            if len(page) < 100:
                break
        fields.update(
            reportId=report_id,
            added_as_blank=True,
            position=max((r["position"] for r in positions), default=0) + 1,
        )
        result = await self.write(q.DIRECT_INSERT, {"object": fields})
        row = result.get("insert_reportedFinding_one")
        if not row or int(row.get("reportId", -1)) != report_id:
            raise DomainError(
                "write_denied", "Ghostwriter did not return a finding in the requested report"
            )
        return {
            "status": "created",
            "finding_id": row["id"],
            "project_id": project_id,
            "report_id": report_id,
            "title": row["title"],
            "complete": row["complete"],
        }

    async def update(
        self,
        project_id: int,
        report_id: int,
        finding_id: int,
        changes: ReportFindingChanges,
        expected_content_hash: str | None = None,
    ) -> dict:
        await self.client.report(project_id, report_id)
        rows = await self.client.page(
            "reportedFinding",
            q.DIRECT_FINDING_FIELDS,
            {"id": {"_eq": finding_id}, "reportId": {"_eq": report_id}},
            limit=1,
        )
        if not rows:
            raise DomainError("forbidden", "Finding is not visible in the requested report")
        current = rows[0]
        if expected_content_hash is not None and digest(current) != expected_content_hash:
            raise DomainError("remote_conflict", "Finding changed since the supplied snapshot")
        fields = await self.fields(
            project_id, changes.model_dump(exclude_unset=True), creating=False
        )
        # Hasura evaluates the comparison and update atomically, preventing lost edits.
        where = {
            "id": {"_eq": finding_id},
            "reportId": {"_eq": report_id},
            "_and": [
                {key: {"_is_null": True} if value is None else {"_eq": value}}
                for key, value in current.items()
                if key not in {"id", "reportId"}
            ],
        }
        result = await self.write(q.DIRECT_UPDATE, {"where": where, "object": fields})
        response = result.get("update_reportedFinding") or {}
        returned = response.get("returning") or []
        if response.get("affected_rows") != 1 or len(returned) != 1:
            raise DomainError(
                "remote_conflict",
                "Finding changed or write permission was denied; read it again before retrying",
            )
        row = returned[0]
        if int(row.get("reportId", -1)) != report_id:
            raise DomainError(
                "write_denied", "Ghostwriter returned a finding outside the requested report"
            )
        return {
            "status": "updated",
            "finding_id": row["id"],
            "project_id": project_id,
            "report_id": report_id,
            "title": row["title"],
            "complete": row["complete"],
        }

    async def write(self, query: str, variables: dict) -> dict:
        try:
            return await self.client.execute(query, variables)
        except DomainError as exc:
            if exc.code in {"upstream_unavailable", "upstream_http_error"}:
                raise DomainError(
                    "write_outcome_unknown",
                    "The write response was not received. Inspect gw_list_findings before retrying; the finding may already have been saved.",
                ) from None
            raise
