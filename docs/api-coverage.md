# Reporting tool coverage

Exactly 23 available tools. GW_ENABLED_TOOLS optionally allows tools; GW_DISABLED_TOOLS removes tools. Missing/empty lists enable all tools.
This file documents available capabilities; generating it does not enable tools or contact Ghostwriter.

| Tool | Category | Writes data | GraphQL operation |
|---|---|---|---|
| `gw_attach_evidence` | evidence | yes | `update_evidence` |
| `gw_attach_library_finding` | findings | yes | `attachFinding` |
| `gw_create_finding` | findings | yes | `insert_reportedFinding_one` |
| `gw_create_report` | reports | yes | `insert_report_one` |
| `gw_delete_evidence` | evidence | yes | `deleteEvidence or scoped delete_evidence + readback` |
| `gw_delete_finding` | findings | yes | `delete_reportedFinding` |
| `gw_download_evidence` | evidence | no | `downloadEvidence` |
| `gw_generate_report` | export | no | `generateReport (base64 JSON and UI URLs)` |
| `gw_get_export` | export | no | `generateReport (decoded current JSON)` |
| `gw_get_finding_options` | discovery | no | `findingSeverity; findingType` |
| `gw_get_project` | discovery | no | `project_by_pk` |
| `gw_get_report` | discovery | no | `report_by_pk; getExtraFieldSpec` |
| `gw_list_evidence` | evidence | no | `evidence` |
| `gw_list_findings` | discovery | no | `reportedFinding` |
| `gw_list_projects` | discovery | no | `project` |
| `gw_list_reports` | discovery | no | `report` |
| `gw_list_templates` | templates | no | `template; project_by_pk` |
| `gw_search_finding_library` | discovery | no | `finding` |
| `gw_select_report_templates` | templates | yes | `template; update_report` |
| `gw_update_executive_summary` | reports | yes | `update_report (_append extra_fields)` |
| `gw_update_finding` | findings | yes | `update_reportedFinding` |
| `gw_update_report` | reports | yes | `update_report` |
| `gw_upload_evidence` | evidence | yes | `uploadEvidence` |

Report export uses a read-only Action even though GraphQL declares it as a mutation.
Office document rendering/download is unsupported; JSON export and UI route URLs are returned.
No schema-wide wrappers, subscriptions, project/report deletion or administrative tools are provided.
