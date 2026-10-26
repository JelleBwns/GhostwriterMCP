"""Source-verified GraphQL documents; validated against the deployed token schema."""

PROJECT = "query Project($id:bigint!){project_by_pk(id:$id){id codename clientId}}"
REPORT = "query Report($id:bigint!){report_by_pk(id:$id){id title projectId extra_fields docxTemplateId pptxTemplateId complete delivered archived}}"
FINDING_FIELDS = "id title description impact mitigation replication_steps severityId reportId complete position affectedEntities cvss_score cvss_vector"
FINDING_TYPES = "query FindingTypes($offset:Int!){findingType(limit:100,offset:$offset,order_by:{id:asc}){id findingType}}"
DIRECT_FINDING_FIELDS = FINDING_FIELDS + " findingTypeId references"
DIRECT_INSERT = "mutation CreateReportFinding($object:reportedFinding_insert_input!){insert_reportedFinding_one(object:$object){id reportId title complete}}"
DIRECT_UPDATE = "mutation EditReportFinding($where:reportedFinding_bool_exp!,$object:reportedFinding_set_input!){update_reportedFinding(where:$where,_set:$object){affected_rows returning{id reportId title complete}}}"

PROJECT_CLIENT = "query ProjectClient($id:bigint!){project_by_pk(id:$id){id clientId}}"
REPORT_INSERT = "mutation CreateReport($object:report_insert_input!){insert_report_one(object:$object){id title projectId complete}}"
REPORT_UPDATE = "mutation UpdateReport($where:report_bool_exp!,$object:report_set_input!){update_report(where:$where,_set:$object){affected_rows returning{id title projectId complete}}}"
SUMMARY_UPDATE = "mutation UpdateSummary($where:report_bool_exp!,$patch:report_append_input!){update_report(where:$where,_append:$patch,_set:{complete:false}){affected_rows returning{id projectId complete}}}"
FINDING_DELETE = "mutation DeleteFinding($id:bigint!,$report:bigint!){delete_reportedFinding(where:{id:{_eq:$id},reportId:{_eq:$report}}){affected_rows returning{id}}}"
LIBRARY_ATTACH = "mutation AttachFinding($finding:Int!,$report:Int!){attachFinding(findingId:$finding,reportId:$report){id}}"
EVIDENCE_UPLOAD = "mutation UploadEvidence($body:String!,$filename:String!,$name:String!,$caption:String!,$description:String,$report:Int!){uploadEvidence(file_base64:$body,filename:$filename,friendly_name:$name,caption:$caption,description:$description,report:$report){id}}"
EVIDENCE_ATTACH = "mutation AttachEvidence($where:evidence_bool_exp!,$object:evidence_set_input!){update_evidence(where:$where,_set:$object){affected_rows returning{id report_id findingId finding{reportId}}}}"
EVIDENCE_DOWNLOAD = "query DownloadEvidence($id:Int!){downloadEvidence(evidenceId:$id){evidenceId filename friendlyName downloadUrl fileBase64}}"
EVIDENCE_DELETE = "mutation DeleteEvidence($id:Int!){deleteEvidence(evidenceId:$id){result}}"
REPORT_GENERATE = (
    "mutation GenerateReport($id:Int!){generateReport(id:$id){reportData docxUrl xlsxUrl pptxUrl}}"
)
REPORT_EXPORT = "mutation RetrieveReportData($id:Int!){generateReport(id:$id){reportData}}"
EVIDENCE_FIELDS = (
    "id report_id findingId finding{reportId} friendlyName caption description uploadDate"
)
TEMPLATE_FIELDS = "id name description clientId docTypeId document reporting_doctype{docType}"

REPORT_FIELD_SPECS = 'query ReportFieldSpecs{getExtraFieldSpec(model:"report"){extraFieldSpec}}'

EVIDENCE_DELETE_ROWS = "mutation DeleteEvidenceRow($where:evidence_bool_exp!){delete_evidence(where:$where){affected_rows returning{id}}}"
