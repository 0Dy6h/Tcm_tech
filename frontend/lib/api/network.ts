import { ApiStatusError, apiFetch, buildApiHeaders } from "./client";
import { getBackendBaseUrl } from "./rag";

export type NetworkAnalysisType = "formula" | "herb";
export type NetworkEvidencePolicy = "direct_human_first" | "mixed_exploratory";

export type NetworkResearchProtocol = {
  disease: "atopic_dermatitis";
  phenotype: string;
  species: "Homo sapiens";
  evidence_policy: NetworkEvidencePolicy;
  query_date: string;
};

export type NetworkDiseaseTargetRecord = {
  raw_identifier: string;
  canonical_symbol: string;
  source_record_id: string;
  source_score: number;
};

export type NetworkDiseaseTargetImport = {
  source_profile: "open_targets_association_v1";
  disease: "atopic_dermatitis";
  phenotype: string;
  species: "Homo sapiens";
  source_database: "Open Targets Platform";
  database_version: string;
  source_query_id: string;
  source_query_label: string;
  source_query_parameters: Record<string, string | number | boolean | string[]>;
  query_date: string;
  retrieved_at: string;
  score_name: "association_score";
  applied_threshold: number;
  threshold_operator: "gte";
  identifier_mapping: "Ensembl target approvedSymbol";
  identifier_mapping_version: string;
  records: NetworkDiseaseTargetRecord[];
};

export type NetworkDiseaseTargetVerifyMetadata = Omit<NetworkDiseaseTargetImport, "records"> & {
  usage_license_note: string;
};

export type NetworkDiseaseTargetImportProvenance = Omit<
  NetworkDiseaseTargetImport,
  "disease" | "phenotype" | "species" | "records"
> & {
  record_count: number;
  provenance_verification_status:
    | "unverified_client_import"
    | "server_verified_raw_artifact";
  import_payload_sha256: string;
  source_artifact_sha256?: string | null;
  source_artifact_filename?: string | null;
  source_artifact_media_type?: string | null;
  usage_license_note?: string | null;
};

export type NetworkCompoundTargetVerifyMetadata = {
  source_profile: "chembl_known_activity_v1";
  compound_id: string;
  compound_label: string;
  species: "Homo sapiens";
  source_database: "ChEMBL";
  database_version: string;
  source_query_id: string;
  source_query_label: string;
  source_query_parameters: {
    assay_organism: "Homo sapiens";
    pchembl_value_min: number;
    standard_type?: string | null;
  };
  query_date: string;
  retrieved_at: string;
  score_name: "pchembl_value";
  applied_threshold: number;
  threshold_operator: "gte";
  identifier_mapping: "ChEMBL target component gene symbol";
  identifier_mapping_version: string;
  usage_license_note: string;
};

export type NetworkCompoundTargetImportProvenance = NetworkCompoundTargetVerifyMetadata & {
  record_count: number;
  provenance_verification_status: "server_verified_raw_artifact";
  import_payload_sha256: string;
  source_artifact_sha256: string;
  source_artifact_filename: string;
  source_artifact_media_type: string;
};

export type NetworkResearchReadiness = {
  protocol_complete: boolean;
  formal_network_ready: boolean;
  blocking_reasons: string[];
};

export type NetworkTargetLineageRow = {
  lineage_row_id?: string | null;
  raw_identifier: string;
  canonical_symbol: string;
  source_database: string;
  database_version?: string | null;
  source_query?: string | null;
  query_date: string;
  retrieved_at?: string | null;
  species: "Homo sapiens";
  source_score?: number | null;
  applied_threshold?: number | null;
  threshold_operator?: "gte" | null;
  score_name?: string | null;
  identifier_mapping: string;
  identifier_mapping_version?: string | null;
  evidence_origin: "mock" | "known_activity" | "predicted" | "mixed" | "disease_association";
  source_record_ids: string[];
  automatic_status: "extracted";
  adjudication_status: "pending" | "accepted" | "excluded" | "needs_review";
  reviewer_id?: string | null;
  reviewed_at?: string | null;
  decision: "unreviewed" | "include" | "exclude";
  decision_rationale?: string | null;
};

export type NetworkTargetIntersectionRow = {
  lineage_row_id: string;
  canonical_symbol: string;
  query_date: string;
  species: "Homo sapiens";
  derivation: "canonical_symbol_exact_match_v1";
  disease_lineage_row_ids: string[];
  compound_lineage_row_ids: string[];
  automatic_status: "derived";
  adjudication_status: "pending" | "accepted" | "excluded" | "needs_review";
  reviewer_id?: string | null;
  reviewed_at?: string | null;
  decision: "unreviewed" | "include" | "exclude";
  decision_rationale?: string | null;
};

export type NetworkTargetLineage = {
  observation_unit: "target_record" | "mixed";
  disease_observation_unit: "source_record";
  compound_observation_unit: "source_record";
  intersection_observation_unit: "canonical_symbol_derivation";
  disease_import_provenance?: NetworkDiseaseTargetImportProvenance | null;
  compound_import_provenance?: NetworkCompoundTargetImportProvenance | null;
  disease_targets: NetworkTargetLineageRow[];
  compound_targets: NetworkTargetLineageRow[];
  intersection_targets: NetworkTargetIntersectionRow[];
  disease_target_count: number;
  compound_target_count: number;
  intersection_target_count: number;
  disease_lineage_row_count: number;
  compound_lineage_row_count: number;
  intersection_lineage_row_count: number;
  warnings: string[];
};

export type NetworkTaskStatus = "queued" | "running" | "completed" | "failed";
export type NetworkDataMode = "mock" | "live";
export type NetworkTargetEvidenceType = "mock" | "known_activity" | "predicted" | "mixed";
export type NetworkEvidenceLevel =
  | "mock_inferred"
  | "predicted"
  | "literature_supported"
  | "omics_validated"
  | "experimental";
export type NetworkPipelineStepStatus = "completed" | "failed" | "skipped" | "degraded";

export type NetworkChain = {
  herb: string;
  formula?: string | null;
  compound: string;
  target: string;
  pathway: string;
  disease: string;
  score: number;
  related_entity_ids: string[];
  evidence_refs?: string[];
  target_evidence_type?: NetworkTargetEvidenceType;
  evidence_level?: NetworkEvidenceLevel | null;
};

export type NetworkDataSource = {
  name: string;
  source_record_id?: string | null;
  url?: string | null;
  retrieved_at?: string | null;
  license_note?: string | null;
  cache_key?: string | null;
  from_cache?: boolean;
};

export type NetworkPipelineStep = {
  name: string;
  status: NetworkPipelineStepStatus;
  duration_ms: number;
  external_request_count: number;
  cache_hit_count: number;
  warning?: string | null;
};

export type NetworkPpiEdge = {
  source: string;
  target: string;
  score: number;
  source_record_id: string;
};

export type EnrichmentTerm = {
  term_id: string;
  term_name: string;
  term_name_zh?: string | null;
  category: string;
  gene_count: number;
  overlap_count: number;
  p_value: number;
  adjusted_p_value: number;
  genes: string[];
};

export type EnrichmentResult = {
  analysis_type: string;
  input_gene_count: number;
  background_gene_count: number;
  terms: EnrichmentTerm[];
  timestamp: string;
};

export type NetworkAnalysisResult = {
  task_id: string;
  source_task_id?: string | null;
  query: string;
  analysis_type: NetworkAnalysisType;
  research_protocol?: NetworkResearchProtocol | null;
  readiness?: NetworkResearchReadiness;
  target_lineage: NetworkTargetLineage;
  data_mode?: NetworkDataMode;
  chains: NetworkChain[];
  enrichment?: EnrichmentResult | null;
  pipeline_steps?: NetworkPipelineStep[];
  data_sources?: NetworkDataSource[];
  ppi_edges?: NetworkPpiEdge[];
  warnings?: string[];
  disclaimer: string;
};

export type NetworkAnalyzeAccepted = {
  task_id: string;
  status: NetworkTaskStatus;
  progress: number;
  data_mode: NetworkDataMode;
};

export type NetworkAdjudicationDecision = "included" | "excluded" | "needs_review";

export type NetworkAdjudicationRecord = {
  lineage_row_id: string;
  decision: NetworkAdjudicationDecision;
  reason: string | null;
  decided_at: string;
};

export type NetworkAdjudicationCounts = {
  included: number;
  excluded: number;
  needs_review: number;
  pending: number;
};

export type NetworkAdjudicationProjection = {
  counts: NetworkAdjudicationCounts;
  current: NetworkAdjudicationRecord[];
};

export type NetworkAdjudicationAccepted = NetworkAdjudicationRecord & {
  adjudication_id: string;
};

export type NetworkAdjudicationSubmission = {
  lineage_row_id: string;
  decision: NetworkAdjudicationDecision;
  reason?: string | null;
};

export type NetworkAssemblyGateBlocker = {
  code: string;
  row_ids: string[];
};

type NetworkAssemblyPlanSummaryBase = {
  plan_id: string;
  policy_id: "source_bound_network_assembly_v1";
  canonical_plan_input_sha256: string;
  selected_intersection_count: number;
  created_at: string;
  assembly_input_ready: true;
  formal_network_ready: false;
};

// Result-envelope projection of the latest plan (D6 read-only consumption
// marker). The bare seal response does not carry this field.
export type NetworkAssemblyPlanSummary = NetworkAssemblyPlanSummaryBase & {
  is_consumed: boolean;
};

export type NetworkAssemblyGateProjection = {
  policy_id: "source_bound_network_assembly_v1";
  state: "blocked" | "assembly_input_ready";
  blockers: NetworkAssemblyGateBlocker[];
  latest_plan: NetworkAssemblyPlanSummary | null;
};

export type NetworkAssemblyPlan = NetworkAssemblyPlanSummaryBase & {
  canonicalization_id: "qiyan_canonical_json_v1";
  task_id: string;
  source_task_id: string;
  plan_sequence: number;
  selected_intersections: Array<{
    lineage_row_id: string;
    canonical_symbol: string;
    frozen_disease_lineage_row_ids: string[];
    frozen_compound_lineage_row_ids: string[];
    selected_disease_lineage_row_ids: string[];
    selected_compound_lineage_row_ids: string[];
  }>;
};

export type NetworkTaskSummary = {
  task_id: string;
  source_task_id: string | null;
  query: string;
  analysis_type: NetworkAnalysisType;
  status: NetworkTaskStatus;
  data_mode: NetworkDataMode;
  formal_network_ready: boolean;
  created_at: string;
};

export type NetworkTaskListResponse = {
  tasks: NetworkTaskSummary[];
};

// ADR-0018 Gate 3：确定性组学 DEG 候选投影（G3-2）。只出候选——不带证据等级、
// 不改就绪状态；唯一升级路径是 append-only 的人工判定流。
export type NetworkOmicsDegCandidate = {
  canonical_symbol: string;
  lineage_row_ids: string[];
  mean_case: number;
  mean_control: number;
  log2fc: number;
  p_value: number;
  adj_p_value: number;
  status: "pending_human_confirmation";
};

export type NetworkOmicsDegProjection = {
  policy_id: string;
  snapshot_id: string;
  accession: string;
  comparison: string;
  case_group: string;
  control_group: string;
  significance_threshold: number;
  log2fc_abs_threshold: number;
  analyzed_probe_count: number;
  analyzed_gene_count: number;
  passing_gene_count: number;
  sample_groups_used: Record<string, number>;
  symbol_mapping_rule: string;
  candidates: NetworkOmicsDegCandidate[];
  formal_network_ready: false;
};

export type NetworkResultResponse = {
  task_id: string;
  status: NetworkTaskStatus;
  progress: number;
  data_mode?: NetworkDataMode;
  result: NetworkAnalysisResult | null;
  error?: string | null;
  warnings?: string[];
  // Append-only manual adjudication projection. Lives on the response, not on
  // the frozen result snapshot, because adjudications never mutate the result.
  adjudication?: NetworkAdjudicationProjection | null;
  // Candidate assembly input projection. This remains separate from scientific readiness.
  assembly_gate?: NetworkAssemblyGateProjection | null;
  // 组学 DEG 候选投影：仅在显式携带 omics 查询参数时由后端计算，默认路径永不触发。
  omics_verification?: NetworkOmicsDegProjection | null;
};

export function buildNetworkAnalyzeUrl() {
  return new URL("/api/network/analyze", getBackendBaseUrl()).toString();
}

export function buildNetworkDiseaseImportVerifyUrl() {
  return new URL("/api/network/disease-import/verify", getBackendBaseUrl()).toString();
}

export function buildNetworkCompoundImportVerifyUrl() {
  return new URL("/api/network/compound-import/verify", getBackendBaseUrl()).toString();
}

export function buildNetworkResultUrl(
  taskId: string,
  options?: { omicsVerification?: boolean; omicsAccession?: string },
) {
  const url = new URL(
    `/api/network/result/${encodeURIComponent(taskId)}`,
    getBackendBaseUrl(),
  );
  if (options?.omicsVerification) {
    url.searchParams.set("omics_verification", "true");
    if (options.omicsAccession) {
      url.searchParams.set("omics_accession", options.omicsAccession);
    }
  }
  return url.toString();
}

export function buildNetworkReportUrl(taskId: string) {
  return new URL(
    `/api/network/result/${encodeURIComponent(taskId)}/report`,
    getBackendBaseUrl(),
  ).toString();
}

export function buildNetworkTasksUrl() {
  return new URL("/api/network/tasks", getBackendBaseUrl()).toString();
}

export function buildNetworkAdjudicationsUrl(taskId: string) {
  return new URL(
    `/api/network/result/${encodeURIComponent(taskId)}/adjudications`,
    getBackendBaseUrl(),
  ).toString();
}

export function buildNetworkAssemblyPlansUrl(taskId: string) {
  return new URL(
    `/api/network/result/${encodeURIComponent(taskId)}/assembly-plans`,
    getBackendBaseUrl(),
  ).toString();
}

export function getNetworkAnalysisTypeLabel(type: NetworkAnalysisType) {
  return type === "herb" ? "单味中药" : "复方";
}

export function getNetworkDataModeLabel(mode: NetworkDataMode | undefined) {
  return mode === "live" ? "真实数据 opt-in" : "Mock 演示数据";
}

export function getNetworkTaskStatusLabel(status: NetworkTaskStatus) {
  switch (status) {
    case "completed":
      return "已完成";
    case "running":
      return "运行中";
    case "failed":
      return "失败";
    default:
      return "排队中";
  }
}

export function getNetworkTaskReadinessLabel(formalNetworkReady: boolean) {
  return formalNetworkReady ? "达到正式科研标准" : "未达正式科研标准";
}

export function getNetworkTargetEvidenceTypeLabel(type: NetworkTargetEvidenceType | undefined) {
  switch (type) {
    case "known_activity":
      return "已知活性证据";
    case "predicted":
      return "预测靶点";
    case "mixed":
      return "已知+预测";
    default:
      return "Mock";
  }
}

export function getNetworkEvidenceLevelLabel(level: NetworkEvidenceLevel | undefined | null) {
  switch (level) {
    case "experimental":
      return "实验证据";
    case "omics_validated":
      return "组学验证";
    case "literature_supported":
      return "文献支撑";
    case "predicted":
      return "预测证据";
    default:
      return "演示推断（未验证）";
  }
}

export async function submitNetworkAnalysis(
  query: string,
  analysisType: NetworkAnalysisType,
  researchProtocol: NetworkResearchProtocol,
  diseaseTargetImport?: NetworkDiseaseTargetImport | null,
): Promise<NetworkAnalyzeAccepted> {
  const body = {
    query: query.trim(),
    analysis_type: analysisType,
    research_protocol: researchProtocol,
    ...(diseaseTargetImport ? { disease_target_import: diseaseTargetImport } : {}),
  };
  const response = await apiFetch(buildNetworkAnalyzeUrl(), {
    method: "POST",
    headers: buildApiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network analyze request failed");
  }

  return response.json();
}

export async function verifyNetworkDiseaseImport(
  query: string,
  analysisType: NetworkAnalysisType,
  evidencePolicy: NetworkEvidencePolicy,
  metadata: NetworkDiseaseTargetVerifyMetadata,
  file: File,
): Promise<NetworkAnalyzeAccepted> {
  const body = new FormData();
  body.set("query", query.trim());
  body.set("analysis_type", analysisType);
  body.set("evidence_policy", evidencePolicy);
  body.set("metadata", JSON.stringify(metadata));
  body.set("file", file);
  const response = await apiFetch(buildNetworkDiseaseImportVerifyUrl(), {
    method: "POST",
    body,
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network disease import verification request failed");
  }

  return response.json();
}

export async function verifyNetworkCompoundImport(
  sourceTaskId: string,
  metadata: NetworkCompoundTargetVerifyMetadata,
  file: File,
): Promise<NetworkAnalyzeAccepted> {
  const body = new FormData();
  body.set("source_task_id", sourceTaskId);
  body.set("metadata", JSON.stringify(metadata));
  body.set("file", file);
  const response = await apiFetch(buildNetworkCompoundImportVerifyUrl(), {
    method: "POST",
    body,
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network compound import verification request failed");
  }

  return response.json();
}

export async function fetchNetworkResult(taskId: string): Promise<NetworkResultResponse> {
  const response = await apiFetch(buildNetworkResultUrl(taskId));

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network result request failed");
  }

  return response.json();
}

export async function fetchNetworkOmicsVerification(
  taskId: string,
  omicsAccession: string,
): Promise<NetworkResultResponse> {
  const response = await apiFetch(
    buildNetworkResultUrl(taskId, { omicsVerification: true, omicsAccession }),
  );

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network omics verification request failed");
  }

  return response.json();
}

export function getNetworkOmicsVerificationSummary(projection: NetworkOmicsDegProjection): string {
  const symbols = projection.candidates
    .map((candidate) => candidate.canonical_symbol)
    .slice(0, 6)
    .join("、");
  const suffix = projection.candidates.length > 6 ? " 等" : "";
  return `候选基因 ${projection.candidates.length} 个` + (symbols ? `：${symbols}${suffix}` : "");
}

export async function fetchNetworkReportMarkdown(taskId: string): Promise<string> {
  const response = await apiFetch(buildNetworkReportUrl(taskId));

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network report request failed");
  }

  return response.text();
}

export async function fetchNetworkTasks(): Promise<NetworkTaskListResponse> {
  const response = await apiFetch(buildNetworkTasksUrl());

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network tasks request failed");
  }

  return response.json();
}

export async function submitNetworkAdjudication(
  taskId: string,
  submission: NetworkAdjudicationSubmission,
): Promise<NetworkAdjudicationAccepted> {
  const trimmedReason = submission.reason?.trim() ?? "";
  const body = {
    lineage_row_id: submission.lineage_row_id,
    decision: submission.decision,
    reason: trimmedReason.length > 0 ? trimmedReason : null,
  };
  const response = await apiFetch(buildNetworkAdjudicationsUrl(taskId), {
    method: "POST",
    headers: buildApiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network adjudication request failed");
  }

  return response.json();
}

export async function sealNetworkAssemblyPlan(taskId: string): Promise<NetworkAssemblyPlan> {
  const response = await apiFetch(buildNetworkAssemblyPlansUrl(taskId), { method: "POST" });
  if (!response.ok) {
    throw new ApiStatusError(response.status, "Network assembly gate blocked");
  }
  return response.json();
}
