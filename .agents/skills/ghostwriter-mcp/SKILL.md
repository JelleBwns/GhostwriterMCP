---
name: ghostwriter-mcp
description: Use enabled Ghostwriter MCP reporting tools to read reports, craft findings, manage report evidence, select templates, and retrieve JSON exports. Applies to reporting work, not general Ghostwriter administration.
---

Use the Ghostwriter MCP connected to the user's instance. It has a fixed catalog of 23 reporting tools. A nonempty `GW_ENABLED_TOOLS` is an allowlist; `GW_DISABLED_TOOLS` is a blacklist and wins on overlaps. If both are missing or empty, all 23 tools are available by default. Tool availability is capability, not authorization for unrelated changes.

## Choose from the exposed tools

- Establish targets using `gw_list_projects`, `gw_get_project`, `gw_list_reports`, `gw_get_report`, and `gw_list_findings`. Confirm the intended project/report IDs before writes.
- Discover instance-specific severity/type IDs with `gw_get_finding_options`; find reference wording with `gw_search_finding_library`. Never guess taxonomy IDs.
- Use `gw_create_finding` or `gw_update_finding` for original content. `gw_attach_library_finding` copies a reusable finding; `gw_delete_finding` deletes one remote finding.
- Use `gw_create_report` only when asked for a new report. `gw_update_report` changes title/complete/delivered/archived metadata, not report ownership, templates or arbitrary JSON. `gw_update_executive_summary` writes an existing narrative extra field.
- Evidence has separate `gw_list_evidence`, `gw_upload_evidence`, `gw_attach_evidence`, `gw_download_evidence` and `gw_delete_evidence` tools.
- `gw_list_templates` and `gw_select_report_templates` work with existing, client-appropriate report templates. `gw_generate_report` requests JSON export; `gw_get_export` retrieves and decodes the current report-data snapshot.

Read the actual exposed tool schema for arguments. There is no raw `arguments`/GraphQL `selection` interface, arbitrary API execution, subscription, project administration, report deletion or template upload tool. Disabled tools cannot be called by guessing names or using old API aliases.

If a needed reporting tool is absent, explain the missing capability and let the owner enable its exact name and restart the MCP process. Do not change `.env`, retrieve the raw token or use shell/HTTP to bypass the allowlist unless the user explicitly asks for configuration work. All tools enforce nonempty `ALLOWED_PROJECTS` and `ALLOWED_CLIENTS` restrictions in addition to upstream permissions. Both lists must match when configured; empty/missing scope lists add no restriction. A permitted project must actually belong to a permitted client. Do not assume tool enablement makes an out-of-scope target accessible.

## Craft content

Base findings and summaries on supplied observations and evidence. Distinguish verified results, analyst conclusions, interpretations and missing information. Never invent successful exploitation, affected systems, screenshots, CVSS scores or vectors.

Finding input is plain text. Create requires title, severity, description and an appropriate finding type unless configured by the owner. Optional impact, remediation and reproduction sections can be completed later. Update only the requested fields; omitted fields are preserved. The connector escapes rich text and saves new/edited findings incomplete for QA.

There is no universal executive-summary field. Use an existing or registered narrative report extra field shown by `gw_get_report`, including its extra_field_specs metadata. `GW_SUMMARY_FIELD`, when configured, pins the permitted field; do not choose a different field. The summary tool preserves unrelated fields and resets report QA status. If the registered narrative field has no value on a newly created report, the summary tool can initialize that value; it does not create or edit field definitions.

## Evidence and exports

Upload accepts base64 bytes, a basename filename, friendly name and caption—not an arbitrary server path or URL. Original bytes are unchanged; no local redaction or storage is performed. Follow the user's data policy for sensitive evidence. Upload first, then attach its remote ID to a finding in the same report. Download returns base64 data; no URL is fetched or local file written by this MCP. Evidence deletion may use a scoped GraphQL fallback when the application Action is absent; storage_cleanup=not_verified means record removal is confirmed but physical-file cleanup is not.

Template selections accept existing DOCX/PPTX template IDs. Omitted selections remain unchanged; explicit null clears a selection. These changes reset report QA status.

`gw_generate_report` returns base64 report-data JSON and Ghostwriter UI route URLs. `gw_get_export` decodes a fresh JSON snapshot, not a stored local artifact. Office rendering/download is unsupported: a URL is not proof that a Word/PowerPoint document was generated. Do not invent an endpoint or browser workaround.

## Check results and scope

A specific user request to write authorizes that requested action. Resolve ambiguous targets first; for deletion, confirm exact scope only when it was not already explicit. Respect no-live-test/offline-only instructions. Do not create a test finding merely because a tool is available.

Check `ok`, `data` and `error`. Report actual remote IDs/statuses. If the result is `write_outcome_unknown`, inspect remote state before repeating it. If `remote_conflict`, reread the record. Permission/schema failures mean the operation is unavailable; they do not authorize broader credentials or bypasses.

For setup and the 23-tool catalog, read [README](../../../README.md). For verified API/version limits, read [API mapping](../../../docs/ghostwriter-api-mapping.md). The owner can inspect the available catalog offline with `python -m gw_reporting tools --json` or `tools --describe <name>`.
