"""Export the 23 available reporting contracts offline; this enables no tools."""

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from gw_reporting.catalog import inventory
from gw_reporting.mcp import CONVENIENCE
from gw_reporting.registry import build_server

MAPPING = {
    "gw_list_projects": "project",
    "gw_get_project": "project_by_pk",
    "gw_list_reports": "report",
    "gw_get_report": "report_by_pk; getExtraFieldSpec",
    "gw_list_findings": "reportedFinding",
    "gw_search_finding_library": "finding",
    "gw_get_finding_options": "findingSeverity; findingType",
    "gw_create_finding": "insert_reportedFinding_one",
    "gw_update_finding": "update_reportedFinding",
    "gw_delete_finding": "delete_reportedFinding",
    "gw_attach_library_finding": "attachFinding",
    "gw_create_report": "insert_report_one",
    "gw_update_report": "update_report",
    "gw_update_executive_summary": "update_report (_append extra_fields)",
    "gw_list_evidence": "evidence",
    "gw_upload_evidence": "uploadEvidence",
    "gw_attach_evidence": "update_evidence",
    "gw_download_evidence": "downloadEvidence",
    "gw_delete_evidence": "deleteEvidence or scoped delete_evidence + readback",
    "gw_list_templates": "template; project_by_pk",
    "gw_select_report_templates": "template; update_report",
    "gw_generate_report": "generateReport (base64 JSON and UI URLs)",
    "gw_get_export": "generateReport (decoded current JSON)",
}


async def main() -> None:
    if set(MAPPING) != set(CONVENIENCE):
        raise ValueError("Coverage mapping must match all 23 tools")
    async with Client(build_server(CONVENIENCE, list(CONVENIENCE))) as client:
        tools = await client.list_tools()
    root = Path(__file__).resolve().parents[1] / "docs"
    (root / "mcp-tools.json").write_text(
        json.dumps([t.model_dump(mode="json") for t in tools], indent=2) + "\n"
    )
    (root / "api-tool-catalog.json").write_text(json.dumps({"tools": inventory()}, indent=2) + "\n")
    rows = [
        "# Reporting tool coverage",
        "",
        "Exactly 23 available tools. GW_ENABLED_TOOLS optionally allows tools; GW_DISABLED_TOOLS removes tools. Missing/empty lists enable all tools.",
        "This file documents available capabilities; generating it does not enable tools or contact Ghostwriter.",
        "",
        "| Tool | Category | Writes data | GraphQL operation |",
        "|---|---|---|---|",
    ]
    for entry in inventory():
        name = entry["name"]
        rows.append(
            f"| `{name}` | {entry['category']} | {'yes' if entry['writes'] else 'no'} | `{MAPPING[name]}` |"
        )
    rows += [
        "",
        "Report export uses a read-only Action even though GraphQL declares it as a mutation.",
        "Office document rendering/download is unsupported; JSON export and UI route URLs are returned.",
        "No schema-wide wrappers, subscriptions, project/report deletion or administrative tools are provided.",
    ]
    (root / "api-coverage.md").write_text("\n".join(rows) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
