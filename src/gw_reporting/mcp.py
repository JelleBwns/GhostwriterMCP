from typing import Literal

from .config import settings
from .direct import DirectAuthoring
from .ghostwriter import Ghostwriter
from .registry import build_server
from .reporting import Reporting
from .schemas import (
    ReportChanges,
    ReportFindingChanges,
    ReportFindingContent,
    ReportTemplateSelection,
    Result,
)

gw = Ghostwriter()
authoring = DirectAuthoring(gw)
reporting = Reporting(gw)
CONVENIENCE = {}


def tool(fn):
    CONVENIENCE[fn.__name__] = fn
    return fn


@tool
async def gw_list_projects(offset: int = 0, limit: int = 100) -> Result:
    """List projects visible to your token within configured client/project scopes."""
    return await gw.page("project", "id codename clientId", gw.project_filter(), offset, limit)


@tool
async def gw_get_project(project_id: int) -> Result:
    """Retrieve an authorized Ghostwriter project."""
    return await gw.project(project_id)


@tool
async def gw_list_reports(project_id: int, offset: int = 0, limit: int = 100) -> Result:
    """List reports belonging to an authorized project."""
    await gw.project(project_id)
    return await gw.page(
        "report", "id title projectId", {"projectId": {"_eq": project_id}}, offset, limit
    )


@tool
async def gw_get_report(project_id: int, report_id: int) -> Result:
    """Retrieve report metadata, extra-field values/specifications and selected template IDs."""
    return await reporting.get_report(project_id, report_id)


@tool
async def gw_list_findings(project_id: int, report_id: int) -> Result:
    """Read all findings from an authorized report, paging the external API."""
    return await gw.all_findings(project_id, report_id)


@tool
async def gw_search_finding_library(project_id: int, search: str, offset: int = 0) -> Result:
    """Search reusable Ghostwriter findings by title; requires upstream library read access."""
    await gw.project(project_id)
    return await gw.page(
        "finding",
        "id title description impact mitigation",
        {"title": {"_ilike": f"%{search}%"}},
        offset,
    )


@tool
async def gw_get_finding_options(project_id: int) -> Result:
    """List actual severity and finding-type IDs to select before creating a finding."""
    return await authoring.options(project_id)


@tool
async def gw_create_finding(
    project_id: int, report_id: int, finding: ReportFindingContent
) -> Result:
    """Create a finding directly in the external Ghostwriter report.

    Writes immediately with your Ghostwriter identity. Supply plain-text content
    drafted by the calling agent, and a finding_type_id from gw_get_finding_options
    unless a default is configured. Do not invent evidence, exploitation or CVSS.
    Optional sections may be left empty for further drafting. Saved complete=false
    for Ghostwriter QA. Reuses identical content when found. No local services or
    separate approval workflow are involved.
    """
    return await authoring.create(project_id, report_id, finding)


@tool
async def gw_update_finding(
    project_id: int,
    report_id: int,
    finding_id: int,
    changes: ReportFindingChanges,
    expected_content_hash: str | None = None,
) -> Result:
    """Edit a report finding directly using its Ghostwriter ID.

    Only supplied fields change; plain text is safely rendered. Ownership checks and
    an atomic comparison prevent cross-report writes and lost concurrent edits.
    Editing resets complete=false for QA. Never invent evidence or CVSS values.
    No local state or separate approval workflow is required.
    """
    return await authoring.update(project_id, report_id, finding_id, changes, expected_content_hash)


@tool
async def gw_delete_finding(project_id: int, report_id: int, finding_id: int) -> Result:
    """Delete one finding from the specified report; cannot delete reports or projects."""
    return await reporting.delete_finding(project_id, report_id, finding_id)


@tool
async def gw_attach_library_finding(
    project_id: int, report_id: int, library_finding_id: int
) -> Result:
    """Copy a reusable library finding into the authorized report using attachFinding."""
    return await reporting.attach_library(project_id, report_id, library_finding_id)


@tool
async def gw_create_report(project_id: int, title: str) -> Result:
    """Create a report in an existing allowed project. Cannot create projects or nested records."""
    return await reporting.create_report(project_id, title)


@tool
async def gw_update_report(project_id: int, report_id: int, changes: ReportChanges) -> Result:
    """Change only title/complete/delivered/archived metadata. Cannot move reports or change templates/summary."""
    return await reporting.update_report(project_id, report_id, changes)


@tool
async def gw_update_executive_summary(
    project_id: int, report_id: int, summary: str, field_name: str | None = None
) -> Result:
    """Save plain-text summary to an existing or registered report field; GW_SUMMARY_FIELD pins the field when configured.

    No universal summary field is assumed. Other extra fields are preserved through
    an atomic JSON patch. The report is marked incomplete for Ghostwriter QA.
    """
    return await reporting.summary(project_id, report_id, summary, field_name)


@tool
async def gw_list_evidence(
    project_id: int, report_id: int, offset: int = 0, limit: int = 100
) -> Result:
    """List report evidence metadata in bounded pages; file bytes are not downloaded."""
    return await reporting.list_evidence(project_id, report_id, offset, limit)


@tool
async def gw_upload_evidence(
    project_id: int,
    report_id: int,
    file_base64: str,
    filename: str,
    friendly_name: str,
    caption: str,
    description: str = "",
) -> Result:
    """Upload supplied base64 bytes to Ghostwriter. Accepts no local paths/URLs.

    File bytes remain unchanged; the upstream form decides supported file types.
    GW_MAX_FILE_BYTES limits size. Upload requires a supported uploadEvidence Action
    and token permissions. Use gw_attach_evidence separately to link a finding.
    """
    return await reporting.upload_evidence(
        project_id, report_id, file_base64, filename, friendly_name, caption, description
    )


@tool
async def gw_attach_evidence(
    project_id: int, report_id: int, evidence_id: int, finding_id: int
) -> Result:
    """Link existing evidence to a finding in the same authorized report; no cross-report moves."""
    return await reporting.attach_evidence(project_id, report_id, evidence_id, finding_id)


@tool
async def gw_download_evidence(project_id: int, report_id: int, evidence_id: int) -> Result:
    """Retrieve evidence bytes as base64 through downloadEvidence; does not fetch URLs or save files."""
    return await reporting.download_evidence(project_id, report_id, evidence_id)


@tool
async def gw_delete_evidence(project_id: int, report_id: int, evidence_id: int) -> Result:
    """Delete one scoped evidence record. Prefer deleteEvidence, use a schema-verified mutation fallback when absent, and report storage-cleanup uncertainty."""
    return await reporting.delete_evidence(project_id, report_id, evidence_id)


@tool
async def gw_list_templates(project_id: int, offset: int = 0, limit: int = 100) -> Result:
    """List global/client templates available to the authorized project, including document types."""
    return await reporting.list_templates(project_id, offset, limit)


@tool
async def gw_select_report_templates(
    project_id: int, report_id: int, selection: ReportTemplateSelection
) -> Result:
    """Select existing DOCX/PPTX templates, or explicitly null selections to clear them.

    Checks project/client visibility and document type; cannot upload or delete
    templates. Unspecified selections are preserved. Report QA status resets.
    """
    return await reporting.select_templates(project_id, report_id, selection)


@tool
async def gw_generate_report(
    project_id: int, report_id: int, document_type: Literal["json", "docx", "pptx", "xlsx"] = "json"
) -> Result:
    """Request report-data JSON export and return base64 plus UI document URLs.

    The verified generateReport Action is read-only export despite GraphQL mutation
    syntax. Office rendering/download is unsupported and returns an explicit error.
    No URLs are fetched and no local export state is stored.
    """
    return await reporting.generate(project_id, report_id, document_type)


@tool
async def gw_get_export(project_id: int, report_id: int) -> Result:
    """Retrieve and decode current report-data JSON through generateReport.

    Stateless read: this retrieves a fresh snapshot, not a saved export artifact.
    It never renders Office documents, fetches URLs or writes files.
    """
    return await reporting.get_export(project_id, report_id)


mcp = build_server(CONVENIENCE, settings().gw_enabled_tools, settings().gw_disabled_tools)
