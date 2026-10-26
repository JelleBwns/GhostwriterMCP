# Verified reporting API mapping

The MCP intentionally exposes 23 reporting functions, not the entire Ghostwriter API. Each is a fixed GraphQL workflow with typed inputs and project/record scope checks. Disabled functions are not registered. General API wrappers, arbitrary selection/mutation inputs and subscription tools have been removed.

## Sources

Public-source snapshot retrieved 2026-10-25, Ghostwriter commit `0f4231b5018db0c7b281e55ddf5d06b217d9243e`:

- [Bundled introspection schema](https://github.com/GhostManager/Ghostwriter/blob/0f4231b5018db0c7b281e55ddf5d06b217d9243e/DOCS/schema.graphql), preserved in tests/fixtures/upstream-schema.json.gz.
- [Action metadata](https://github.com/GhostManager/Ghostwriter/blob/0f4231b5018db0c7b281e55ddf5d06b217d9243e/hasura-docker/metadata/actions.graphql), preserved in tests/fixtures/upstream-actions.graphql. Action definitions supplement the bundled introspection snapshot for offline tests.
- [Authentication documentation](https://www.ghostwriter.wiki/features/graphql-api/authentication), [GraphQL examples](https://www.ghostwriter.wiki/features/graphql-api/graphql-usage-examples).
- Prior research also inspected the [MCP PoC](https://github.com/GhostManager/Ghostwriter/pull/690) and [official agent skills](https://github.com/GhostManager/ghostwriter-skills); neither establishes a bearer-authenticated Office rendering interface.

[Source manifest](api-source-manifest.json) records hashes. These are source/contract checks, not a live compatibility certification. The initial implementation used offline contracts. A subsequent explicitly authorized live run on a dedicated test client exercised all 23 tools; only test-created objects were mutated. Local test results are kept under ignored artifacts/.

## API operations used

| Area | Verified public GraphQL interface | MCP handling |
|---|---|---|
| Project discovery | project, project_by_pk | Client/project-filtered projects; ID/codename/clientId. Client ID is read internally for template filtering. |
| Report discovery | report, report_by_pk | Report belongs to authorized project; reads metadata, extra fields, template IDs and status flags. |
| Report creation | insert_report_one with report_insert_input | Fixed title/project/date/default status fields; include_bloodhound_data=false is included only when the live input schema supports it. No nested objects or project creation. Raw API creation does not promise the full Django UI initialization workflow. |
| Report metadata | update_report with report_set_input | Typed title/complete/delivered/archived only, scoped to project/report and prior values. |
| Executive summary | update_report with report_append_input | Atomic _append of one existing/registered narrative extra-field key. Registered-but-unpopulated fields are verified through getExtraFieldSpec and guarded with _has_key absence; existing keys compare old values. No universal executiveSummary field is invented. Other keys are preserved; complete=false. |
| Report findings | reportedFinding, insert_reportedFinding_one, update_reportedFinding, delete_reportedFinding | Existing scoped discovery/create/update, plus deletion of one finding by ID/report. No bulk or arbitrary mutation input. |
| Library | finding, attachFinding(findingId,reportId) | Search library; copy one library finding into a report and verify destination membership. No library edits/deletion. |
| Taxonomy | findingSeverity, findingType | Instance-specific IDs; no hardcoded severity/type ID mapping. |
| Evidence metadata | evidence | Scope by direct report_id, or by finding.reportId when the direct report pointer is null; verify target report membership. |
| Evidence upload | uploadEvidence(file_base64, filename, friendly_name, caption, description, report) | Verified in Action metadata; absent from the bundled introspection snapshot. Enabled only when deployed role schema supports it. Base64/size/basename validation; bytes unmodified, no local persistence. Upstream form restricts types. |
| Evidence linking | update_evidence(_set:{findingId}) | Existing evidence and finding must share report. Nullable report-pointer schemas clear the direct pointer for exclusive finding ownership; legacy non-null schemas retain it. Scoped conditional update and association readback apply. |
| Evidence download | downloadEvidence(evidenceId) | Return base64, metadata, size/hash. Never fetch returned downloadUrl. |
| Evidence deletion | deleteEvidence(evidenceId) | Prefer application Action; only on schema unavailability use the verified, report-scoped delete_evidence mutation. Verify row absence. Fallback explicitly reports physical storage cleanup as unverified; no direct database/storage access is used. |
| Templates | template {id name description clientId docTypeId document reporting_doctype{docType}} | Filter global/project-client templates; select existing DOCX/PPTX IDs with document-type checks. No upload or delete. |
| Template selection | update_report(_set:{docxTemplateId,pptxTemplateId}) | Scoped conditional update; preserve omitted selections, allow explicit null clearing; complete=false. |
| Report-data generation | generateReport(id) {reportData docxUrl xlsxUrl pptxUrl} | Read-only export Action despite mutation syntax. Returns validated base64 JSON and UI route URLs. |
| Export retrieval | generateReport(id) {reportData} | Retrieve a fresh snapshot and decode JSON. No existing local artifact is implied. |

Generated [23-tool coverage table](api-coverage.md) and [schemas](mcp-tools.json) give exact tool names and inputs/outputs.

## Authentication, version and failure behavior

Use POST /v1/graphql with Authorization: Bearer TOKEN. User API tokens inherit user permissions; service tokens have independent grants and may not permit writes/Actions. Seeing a schema field does not prove row-level permission. The upstream integration identity remains authoritative for permissions and deletion cascade behavior. Internal Django Action routes and Hasura admin secrets are not used.

The connector introspects with the configured token when an enabled function is called, validates its complete document/variables, and then executes it. Missing capabilities return unsupported_operation. Recognized naming alternatives (extra_fields/extraFields, added_as_blank/addedAsBlank, cvss_score/cvssScore, cvss_vector/cvssVector, report_id/reportId) are mapped only when the live schema confirms them. No offline schema fallback is used to infer deployed capabilities.

Metadata edits, summary writes, template selection and record attachment have dedicated input types; enabling one cannot provide an arbitrary _set or nested-create payload to another. Tool exposure uses the optional GW_ENABLED_TOOLS allowlist minus GW_DISABLED_TOOLS blacklist; blacklist entries win, and absent/empty tool lists enable all 23 tools. Optional ALLOWED_PROJECTS and ALLOWED_CLIENTS lists apply to every reporting workflow and intersect when both are nonempty. Missing/empty scope lists impose no restriction at that level. Client identity is checked from the actual project record before report access or changes.

Mutations are never automatically retried. An ambiguous network result is write_outcome_unknown, requiring inspection before retrying. Readback is used for library attachment/evidence deletion where needed; failed verification is not reported as success. Identity comparisons and affected-row checks prevent zero-row responses from being misreported as writes.

## Not covered

There are no project administration/deletion, report deletion, user/token management, arbitrary API, subscription, infrastructure, operation-log, library mutation or template upload/deletion tools. Their underlying API presence is not a promise of MCP availability.

The generateReport handler serializes report-data JSON and returns Django UI route URLs. Reviewed Office rendering routes rely on Django web-session permissions; no verified public bearer rendering/download interface was established. DOCX/PPTX/XLSX requests therefore return explicit unsupported-operation errors. No browser automation or undocumented endpoint substitutes are implemented.
