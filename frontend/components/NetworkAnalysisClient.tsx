"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { CloseOutlined, DownloadOutlined, UploadOutlined } from "@ant-design/icons";
import { useSearchParams } from "next/navigation";

import {
  fetchNetworkReportMarkdown,
  fetchNetworkOmicsVerification,
  fetchNetworkResult,
  getNetworkOmicsVerificationSummary,
  getNetworkAnalysisTypeLabel,
  getNetworkDataModeLabel,
  getNetworkEvidenceLevelLabel,
  getNetworkTargetEvidenceTypeLabel,
  NetworkAdjudicationDecision,
  NetworkAdjudicationProjection,
  NetworkAdjudicationRecord,
  NetworkAnalysisResult,
  NetworkAnalysisType,
  NetworkAssemblyGateProjection,
  NetworkEvidencePolicy,
  NetworkResearchProtocol,
  NetworkTargetLineageRow,
  sealNetworkAssemblyPlan,
  submitNetworkAdjudication,
  submitNetworkAnalysis,
  verifyNetworkCompoundImport,
  verifyNetworkDiseaseImport,
} from "../lib/api/network";
import {
  buildNetworkAdjudicationDecisionMap,
  countNetworkLineageRows,
  getNetworkAdjudicationButtonLabel,
  getNetworkAdjudicationDecisionLabel,
  getNetworkAdjudicationInFlightMessage,
  getNetworkAdjudicationUnavailableReason,
} from "../lib/network-adjudication";
import { ApiStatusError, describeApiError } from "../lib/api/client";
import { toLocalDateInputValue } from "../lib/format-date";
import { truncateLabel } from "../lib/format-text";
import { parseNetworkTaskIdParam } from "../lib/network-tasks";
import {
  buildNetworkFocusHref,
  fetchNetworkEntities,
  getEntityKindLabel,
  type NetworkEntity,
} from "../lib/api/network-entities";
import { buildNetworkReportFileName } from "../lib/network-report-export";
import { getSurfaceCardStyle, getSurfaceSectionStyle } from "../lib/ui/surfaces";
import EntityChips from "./EntityChips";
import NetworkGraph from "./NetworkGraph";
import StatusPanel from "./StatusPanel";

type NetworkPhase = "idle" | "submitting" | "polling" | "completed" | "error";

const POLL_INTERVAL_MS = 800;
const MAX_POLL_ATTEMPTS = 10;
// 与后端 NetworkAnalyzeRequest / NetworkResearchProtocol 字段约束一致（backend/app/schemas/network.py）。
const NETWORK_QUERY_MAX_LENGTH = 100;
const NETWORK_PHENOTYPE_MIN_LENGTH = 4;
const NETWORK_PHENOTYPE_MAX_LENGTH = 200;

function formatScore(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatLineageScore(value: number, scoreName?: string | null) {
  return scoreName === "pchembl_value" ? String(value) : formatScore(value);
}

function getAssemblyGateBlockerLabel(code: string) {
  const labels: Record<string, string> = {
    adjudication_incomplete: "仍有未判定或待复核的 lineage 行",
    no_included_intersection: "没有可纳入的派生交集",
    included_intersection_missing_backing: "纳入交集缺少双侧已纳入来源行",
    broken_parent_link: "疾病父任务链接不可审计",
    protocol_mismatch: "父子任务研究协议不一致",
    disease_provenance_unverified: "疾病来源未通过服务端 raw-artifact 核验",
    compound_provenance_unverified: "成分来源未通过服务端 raw-artifact 核验",
    snapshot_only_boundary_violated: "冻结快照包含不应生成的网络输出",
    task_not_completed: "任务尚未完成",
    not_compound_child: "当前任务不是双侧来源的成分 child",
    assembly_input_capacity_exceeded: "任务规模超过当前受控封存上限",
  };
  return labels[code] ?? code;
}

type RowAdjudicationControls = {
  enabled: boolean;
  // Locking is per row, not page-wide: reviewing dozens of rows must not serialize
  // behind one in-flight submission.
  busyRowIds: ReadonlySet<string>;
  decisionMap: Map<string, NetworkAdjudicationRecord>;
  onSubmit: (rowId: string, decision: NetworkAdjudicationDecision, reason: string) => void;
};

function getAdjudicationPillStyle(decision: NetworkAdjudicationDecision | null) {
  switch (decision) {
    case "included":
      return { color: "#0f766e", background: "rgba(204, 251, 241, 0.72)", border: "1px solid rgba(13, 148, 136, 0.3)" };
    case "excluded":
      return { color: "#b91c1c", background: "rgba(254, 226, 226, 0.78)", border: "1px solid rgba(185, 28, 28, 0.28)" };
    case "needs_review":
      return { color: "#92400e", background: "rgba(255, 251, 235, 0.9)", border: "1px solid rgba(180, 83, 9, 0.28)" };
    default:
      return { color: "var(--qiyan-muted)", background: "var(--qiyan-surface-3)", border: "1px solid var(--qiyan-line)" };
  }
}

const ADJUDICATION_DECISIONS: NetworkAdjudicationDecision[] = ["included", "excluded", "needs_review"];

function LineageAdjudicationCell({
  rowId,
  controls,
}: {
  rowId: string | null | undefined;
  controls: RowAdjudicationControls;
}) {
  if (!rowId) {
    return <span style={{ color: "var(--qiyan-muted)", fontSize: 12 }}>无稳定 ID，不可判定</span>;
  }
  const record = controls.decisionMap.get(rowId);
  // Remount on each newly recorded decision so the draft reason input resets
  // instead of leaving stale text beside the persisted reason.
  return (
    <LineageAdjudicationForm
      key={record?.decided_at ?? "undecided"}
      rowId={rowId}
      controls={controls}
    />
  );
}

function LineageAdjudicationForm({
  rowId,
  controls,
}: {
  rowId: string;
  controls: RowAdjudicationControls;
}) {
  const [reason, setReason] = useState("");
  const record = controls.decisionMap.get(rowId);
  const decision = record?.decision ?? null;
  const busy = controls.busyRowIds.has(rowId);
  return (
    <div style={{ display: "grid", gap: 6, minWidth: 230 }} aria-label={`人工判定 ${rowId}`}>
      <span
        style={{
          ...getAdjudicationPillStyle(decision),
          justifySelf: "start",
          borderRadius: 999,
          fontSize: 12,
          fontWeight: 700,
          padding: "2px 10px",
        }}
      >
        {decision ? getNetworkAdjudicationDecisionLabel(decision) : "未判定"}
      </span>
      {record?.reason ? (
        <span style={{ color: "var(--qiyan-muted)", fontSize: 12, lineHeight: 1.5 }} title={record.reason}>
          理由：{record.reason}
        </span>
      ) : null}
      {controls.enabled ? (
        <>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {ADJUDICATION_DECISIONS.map((option) => (
              <button
                key={option}
                type="button"
                disabled={busy}
                onClick={() => controls.onSubmit(rowId, option, reason)}
                style={{
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 6,
                  background: busy ? "var(--qiyan-surface-3)" : "var(--qiyan-surface)",
                  color: "var(--qiyan-ink)",
                  fontSize: 12,
                  fontWeight: 700,
                  minHeight: 30,
                  padding: "4px 10px",
                  cursor: busy ? "not-allowed" : "pointer",
                }}
              >
                {getNetworkAdjudicationButtonLabel(option)}
              </button>
            ))}
          </div>
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="理由（可选）"
            aria-label={`判定理由 ${rowId}`}
            style={{
              border: "1px solid var(--qiyan-line)",
              borderRadius: 6,
              fontSize: 12,
              padding: "6px 8px",
            }}
          />
        </>
      ) : null}
    </div>
  );
}

function TargetLineageTable({
  rows,
  adjudication,
}: {
  rows: NetworkTargetLineageRow[];
  adjudication: RowAdjudicationControls;
}) {
  return (
    <div style={{ maxWidth: "100%", overflowX: "auto", marginBottom: 16 }}>
      <table
        style={{
          width: "100%",
          minWidth: 1900,
          borderCollapse: "collapse",
          fontSize: 13,
          textAlign: "left",
        }}
      >
        <thead>
          <tr style={{ borderBottom: "2px solid var(--qiyan-line)" }}>
            {[
              "Lineage row ID",
              "原始 ID",
              "标准符号",
              "来源 / 数据库版本",
              "来源查询",
              "查询 / 获取时间",
              "Score / 阈值",
              "标识符映射 / 版本",
              "证据类型",
              "自动状态",
              "人工判定",
              "决策",
              "来源记录",
              "Reviewer 判定操作",
            ].map((heading) => (
              <th
                key={heading}
                scope="col"
                style={{ padding: "10px 8px", color: "var(--qiyan-muted)", whiteSpace: "nowrap" }}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.lineage_row_id ?? `${row.source_database}-${row.canonical_symbol}-${row.source_record_ids.join("-")}`}
              style={{ borderBottom: "1px solid var(--qiyan-line)" }}
            >
              <td
                title={row.lineage_row_id ?? "legacy row without stable ID"}
                style={{ padding: "10px 8px", fontFamily: "monospace", maxWidth: 220, overflowWrap: "anywhere" }}
              >
                {row.lineage_row_id ?? "legacy"}
              </td>
              <td style={{ padding: "10px 8px", fontFamily: "monospace" }}>{row.raw_identifier}</td>
              <td style={{ padding: "10px 8px", color: "var(--qiyan-ink)", fontWeight: 800 }}>
                {row.canonical_symbol}
              </td>
              <td style={{ padding: "10px 8px" }}>
                {row.source_database} / {row.database_version ?? "未冻结"}
              </td>
              <td style={{ padding: "10px 8px", fontFamily: "monospace" }}>
                {row.source_query ?? "无"}
              </td>
              <td style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>
                {row.query_date} / {row.retrieved_at ?? "无"}
              </td>
              <td style={{ padding: "10px 8px", whiteSpace: "nowrap" }}>
                {row.score_name ?? "未声明"}: {row.source_score == null ? "无" : formatLineageScore(row.source_score, row.score_name)} /{" "}
                {row.applied_threshold == null
                  ? "未声明"
                  : `${row.threshold_operator ?? "gte"} ${formatLineageScore(row.applied_threshold, row.score_name)}`}
              </td>
              <td style={{ padding: "10px 8px" }}>
                {row.identifier_mapping} / {row.identifier_mapping_version ?? "未冻结"}
              </td>
              <td style={{ padding: "10px 8px" }}>{row.evidence_origin}</td>
              <td style={{ padding: "10px 8px" }}>{row.automatic_status}</td>
              <td style={{ padding: "10px 8px", color: "#92400e", fontWeight: 700 }}>
                {row.adjudication_status}
              </td>
              <td style={{ padding: "10px 8px" }}>{row.decision}</td>
              <td style={{ padding: "10px 8px", fontFamily: "monospace" }}>
                {row.source_record_ids.join(", ") || "无"}
              </td>
              <td style={{ padding: "10px 8px", verticalAlign: "top" }}>
                <LineageAdjudicationCell rowId={row.lineage_row_id} controls={adjudication} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function NetworkAnalysisClient() {
  const searchParams = useSearchParams();
  const focusEntityId = searchParams.get("focus");
  const taskIdParam = parseNetworkTaskIdParam(searchParams.get("task_id"));
  const [query, setQuery] = useState("消风散");
  const [analysisType, setAnalysisType] = useState<NetworkAnalysisType>("formula");
  const [phenotype, setPhenotype] = useState("特应性皮炎伴 2 型炎症与皮肤屏障异常");
  const [evidencePolicy, setEvidencePolicy] =
    useState<NetworkEvidencePolicy>("direct_human_first");
  const [queryDate, setQueryDate] = useState(() => toLocalDateInputValue(new Date()));
  const [diseaseRawArtifact, setDiseaseRawArtifact] = useState<File | null>(null);
  const [diseaseImportFileName, setDiseaseImportFileName] = useState<string | null>(null);
  const [openTargetsRelease, setOpenTargetsRelease] = useState("25.06");
  const [diseaseThreshold, setDiseaseThreshold] = useState("0.6");
  const [identifierMappingVersion, setIdentifierMappingVersion] = useState("25.06");
  const [retrievedAt, setRetrievedAt] = useState(() => new Date().toISOString());
  const [usageLicenseNote, setUsageLicenseNote] = useState(
    "Open Targets Platform data usage terms apply.",
  );
  const [compoundRawArtifact, setCompoundRawArtifact] = useState<File | null>(null);
  const [compoundImportFileName, setCompoundImportFileName] = useState<string | null>(null);
  const [chemblCompoundId, setChemblCompoundId] = useState("CHEMBL1201587");
  const [chemblCompoundLabel, setChemblCompoundLabel] = useState("Quercetin");
  const [chemblRelease, setChemblRelease] = useState("34");
  const [chemblThreshold, setChemblThreshold] = useState("6.0");
  const [chemblMappingVersion, setChemblMappingVersion] = useState("34");
  const [chemblRetrievedAt, setChemblRetrievedAt] = useState(() => new Date().toISOString());
  const [chemblUsageLicenseNote, setChemblUsageLicenseNote] = useState(
    "ChEMBL data; see database terms.",
  );
  const [phase, setPhase] = useState<NetworkPhase>("idle");
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<NetworkAnalysisResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorHint, setErrorHint] = useState<{ href: string; label: string } | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [adjudication, setAdjudication] = useState<NetworkAdjudicationProjection | null>(null);
  const [assemblyGate, setAssemblyGate] = useState<NetworkAssemblyGateProjection | null>(null);
  const [assemblyPlanError, setAssemblyPlanError] = useState<string | null>(null);
  const [assemblyPlanBusy, setAssemblyPlanBusy] = useState(false);
  const [adjudicationError, setAdjudicationError] = useState<string | null>(null);
  const [adjudicationBusyRowIds, setAdjudicationBusyRowIds] = useState<ReadonlySet<string>>(
    () => new Set<string>(),
  );
  // 组学验证（omics DEG 投影）入口状态：登录号 + 请求态 + 结果摘要/诚实反馈。
  const [omicsAccession, setOmicsAccession] = useState("");
  const [omicsBusy, setOmicsBusy] = useState(false);
  const [omicsSummary, setOmicsSummary] = useState<string | null>(null);
  const [omicsMessage, setOmicsMessage] = useState<string | null>(null);
  const adjudicationBusyRowIdsRef = useRef<ReadonlySet<string>>(new Set<string>());
  // Identifies the task the user is currently looking at, so a late response from a
  // superseded task can never paint its lineage or decisions over the current one.
  const activeTaskIdRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const appliedFocusRef = useRef<string | null>(null);
  const appliedTaskIdRef = useRef<string | null>(null);
  const diseaseImportInputRef = useRef<HTMLInputElement | null>(null);
  const compoundImportInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  function beginRun() {
    // Invalidate any in-flight poll/refetch before a new run so its late response
    // cannot land on top of the run the reviewer just started.
    activeTaskIdRef.current = null;
    setErrorMessage(null);
    setErrorHint(null);
    setInfoMessage(null);
    setResult(null);
    setAdjudication(null);
    setAssemblyGate(null);
    setAssemblyPlanError(null);
    setAdjudicationError(null);
    setProgress(0);
  }

  async function pollUntilCompleted(taskId: string) {
    activeTaskIdRef.current = taskId;
    for (let attempt = 0; attempt < MAX_POLL_ATTEMPTS; attempt += 1) {
      // Bail out as soon as a newer task supersedes this one, so a slow poll for an
      // abandoned task cannot overwrite the task the reviewer is now viewing.
      if (!mountedRef.current || activeTaskIdRef.current !== taskId) {
        return;
      }
      try {
        const polled = await fetchNetworkResult(taskId);
        if (!mountedRef.current || activeTaskIdRef.current !== taskId) {
          return;
        }
        setProgress(polled.progress);
        if (polled.status === "failed") {
          setErrorMessage(polled.error ?? "网络分析任务失败，请检查真实数据来源与缓存配置。");
          setPhase("error");
          return;
        }
        if (polled.status === "completed" && polled.result) {
          setResult(polled.result);
          setAdjudication(polled.adjudication ?? null);
          setAssemblyGate(polled.assembly_gate ?? null);
          setPhase("completed");
          return;
        }
      } catch (error) {
        if (!mountedRef.current) {
          return;
        }
        if (error instanceof ApiStatusError && error.status === 404) {
          setErrorMessage("未找到该任务：任务可能不存在、已被删除，或不属于当前环境。");
          setErrorHint({ href: "/tasks", label: "← 回到我的研究" });
        } else if (error instanceof ApiStatusError) {
          setErrorMessage(`轮询任务结果失败（HTTP ${error.status}），请稍后重试。`);
        } else {
          setErrorMessage("轮询任务结果失败，请确认后端服务已启动。");
        }
        setPhase("error");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    if (mountedRef.current) {
      setErrorMessage("任务在限定轮询次数内未完成，请稍后重试。");
      setPhase("error");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setErrorMessage("请输入复方或单味中药名称。");
      setPhase("error");
      return;
    }
    if (!phenotype.trim() || !queryDate) {
      setErrorMessage("请先填写明确研究表型与查询日期，再运行网络药理学任务。");
      setPhase("error");
      return;
    }
    if (trimmedQuery.length > NETWORK_QUERY_MAX_LENGTH) {
      setErrorMessage(`分析对象过长（上限 ${NETWORK_QUERY_MAX_LENGTH} 字），请缩短后重试。`);
      setPhase("error");
      return;
    }
    const trimmedPhenotype = phenotype.trim();
    if (
      trimmedPhenotype.length < NETWORK_PHENOTYPE_MIN_LENGTH ||
      trimmedPhenotype.length > NETWORK_PHENOTYPE_MAX_LENGTH
    ) {
      setErrorMessage(
        `研究表型需为 ${NETWORK_PHENOTYPE_MIN_LENGTH}-${NETWORK_PHENOTYPE_MAX_LENGTH} 字，请写明本次研究的 AD 表型或机制边界。`,
      );
      setPhase("error");
      return;
    }
    if (queryDate > toLocalDateInputValue(new Date())) {
      setErrorMessage("查询日期不能晚于今天，请核对后再运行。");
      setPhase("error");
      return;
    }

    const researchProtocol: NetworkResearchProtocol = {
      disease: "atopic_dermatitis",
      phenotype: trimmedPhenotype,
      species: "Homo sapiens",
      evidence_policy: evidencePolicy,
      query_date: queryDate,
    };
    if (diseaseRawArtifact) {
      await runVerifiedAnalysis(trimmedQuery, analysisType, researchProtocol, diseaseRawArtifact);
      return;
    }

    await runAnalysis(trimmedQuery, analysisType, researchProtocol);
  }

  async function onDiseaseImportChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setDiseaseRawArtifact(file);
    setDiseaseImportFileName(file.name);
    setErrorMessage(null);
    if (phase === "error") {
      setPhase("idle");
    }
  }

  function removeDiseaseImport() {
    setDiseaseRawArtifact(null);
    setDiseaseImportFileName(null);
    if (diseaseImportInputRef.current) {
      diseaseImportInputRef.current.value = "";
    }
  }

  function onCompoundImportChange(event: ChangeEvent<HTMLInputElement>) {
    if (isBusy) {
      return;
    }
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setCompoundRawArtifact(file);
    setCompoundImportFileName(file.name);
    setErrorMessage(null);
  }

  function removeCompoundImport() {
    if (isBusy) {
      return;
    }
    setCompoundRawArtifact(null);
    setCompoundImportFileName(null);
    if (compoundImportInputRef.current) {
      compoundImportInputRef.current.value = "";
    }
  }

  async function onSubmitCompoundImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBusy) {
      return;
    }
    const sourceResult = result;
    const diseaseProvenance = sourceResult?.target_lineage.disease_import_provenance;
    if (
      !sourceResult ||
      !sourceResult.research_protocol ||
      diseaseProvenance?.provenance_verification_status !== "server_verified_raw_artifact"
    ) {
      setErrorMessage("请先完成服务端核验的疾病靶点任务，再导入成分靶点原始 artifact。");
      setPhase("error");
      return;
    }
    if (!compoundRawArtifact) {
      setErrorMessage("请选择 ChEMBL 成分靶点原始文件。");
      setPhase("error");
      return;
    }
    const appliedThreshold = Number(chemblThreshold);
    if (!Number.isFinite(appliedThreshold) || appliedThreshold < 0 || appliedThreshold > 20) {
      setErrorMessage("pChEMBL 阈值必须在 0 到 20 之间。");
      setPhase("error");
      return;
    }
    if (
      !chemblCompoundId.trim() ||
      !chemblCompoundLabel.trim() ||
      !chemblRelease.trim() ||
      !chemblMappingVersion.trim() ||
      !chemblUsageLicenseNote.trim()
    ) {
      setErrorMessage("请完整填写 ChEMBL compound、release、mapping 与 usage 信息。");
      setPhase("error");
      return;
    }

    // Keeps the parent result on screen while the child task is created, but still
    // invalidates any in-flight poll so its late response cannot win.
    activeTaskIdRef.current = null;
    setErrorMessage(null);
    setAdjudication(null);
    setAssemblyGate(null);
    setAssemblyPlanError(null);
    setAdjudicationError(null);
    setProgress(0);
    setPhase("submitting");
    try {
      const accepted = await verifyNetworkCompoundImport(
        sourceResult.task_id,
        {
          source_profile: "chembl_known_activity_v1",
          compound_id: chemblCompoundId.trim(),
          compound_label: chemblCompoundLabel.trim(),
          species: "Homo sapiens",
          source_database: "ChEMBL",
          database_version: chemblRelease.trim(),
          source_query_id: chemblCompoundId.trim(),
          source_query_label: chemblCompoundLabel.trim(),
          source_query_parameters: {
            assay_organism: "Homo sapiens",
            standard_type: "IC50",
            pchembl_value_min: appliedThreshold,
          },
          query_date: sourceResult.research_protocol.query_date,
          retrieved_at: chemblRetrievedAt,
          score_name: "pchembl_value",
          applied_threshold: appliedThreshold,
          threshold_operator: "gte",
          identifier_mapping: "ChEMBL target component gene symbol",
          identifier_mapping_version: chemblMappingVersion.trim(),
          usage_license_note: chemblUsageLicenseNote.trim(),
        },
        compoundRawArtifact,
      );
      if (!mountedRef.current) {
        return;
      }
      setProgress(accepted.progress);
      setPhase("polling");
      await pollUntilCompleted(accepted.task_id);
    } catch {
      if (!mountedRef.current) {
        return;
      }
      setErrorMessage("服务端核验 ChEMBL 原始文件失败，请检查 source task、release、阈值与文件内容。");
      setPhase("error");
    }
  }

  async function runVerifiedAnalysis(
    submitQuery: string,
    submitType: NetworkAnalysisType,
    researchProtocol: NetworkResearchProtocol,
    rawArtifact: File,
  ) {
    const appliedThreshold = Number(diseaseThreshold);
    if (!Number.isFinite(appliedThreshold) || appliedThreshold < 0 || appliedThreshold > 1) {
      setErrorMessage("疾病关联阈值必须在 0 到 1 之间。");
      setPhase("error");
      return;
    }
    beginRun();
    setPhase("submitting");
    try {
      const accepted = await verifyNetworkDiseaseImport(
        submitQuery,
        submitType,
        researchProtocol.evidence_policy,
        {
          source_profile: "open_targets_association_v1",
          disease: researchProtocol.disease,
          phenotype: researchProtocol.phenotype,
          species: researchProtocol.species,
          source_database: "Open Targets Platform",
          database_version: openTargetsRelease.trim(),
          source_query_id: "EFO_0000274",
          source_query_label: "atopic eczema",
          source_query_parameters: { datatype: "overall" },
          query_date: researchProtocol.query_date,
          retrieved_at: retrievedAt,
          score_name: "association_score",
          applied_threshold: appliedThreshold,
          threshold_operator: "gte",
          identifier_mapping: "Ensembl target approvedSymbol",
          identifier_mapping_version: identifierMappingVersion.trim(),
          usage_license_note: usageLicenseNote.trim(),
        },
        rawArtifact,
      );
      if (!mountedRef.current) {
        return;
      }
      setProgress(accepted.progress);
      setPhase("polling");
      await pollUntilCompleted(accepted.task_id);
    } catch {
      if (!mountedRef.current) {
        return;
      }
      setErrorMessage("服务端核验 Open Targets 原始文件失败，请检查 release、阈值与文件内容。");
      setPhase("error");
    }
  }

  async function onDownloadReport() {
    if (!result) {
      return;
    }

    try {
      const markdown = await fetchNetworkReportMarkdown(result.task_id);
      const fileName = buildNetworkReportFileName(result.task_id);
      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      setErrorMessage(describeApiError(error, "导出报告"));
      setPhase("error");
    }
  }

  async function runAnalysis(
    submitQuery: string,
    submitType: NetworkAnalysisType,
    researchProtocol: NetworkResearchProtocol = {
      disease: "atopic_dermatitis",
      phenotype: phenotype.trim(),
      species: "Homo sapiens",
      evidence_policy: evidencePolicy,
      query_date: queryDate,
    },
  ) {
    beginRun();
    setPhase("submitting");

    try {
      const accepted = await submitNetworkAnalysis(
        submitQuery,
        submitType,
        researchProtocol,
        null,
      );
      if (!mountedRef.current) {
        return;
      }
      setProgress(accepted.progress);
      setPhase("polling");
      await pollUntilCompleted(accepted.task_id);
    } catch (error) {
      if (!mountedRef.current) {
        return;
      }
      if (error instanceof ApiStatusError && error.status === 422) {
        setErrorMessage(
          "提交被服务端校验拒绝：请核对分析对象与研究表型（4-200 字）、查询日期后重试。",
        );
      } else if (error instanceof ApiStatusError) {
        setErrorMessage(`提交分析任务失败（HTTP ${error.status}），请稍后重试。`);
      } else {
        setErrorMessage("提交分析任务失败，请确认后端服务已启动。");
      }
      setPhase("error");
    }
  }

  async function onSubmitAdjudication(
    rowId: string,
    decision: NetworkAdjudicationDecision,
    reason: string,
  ) {
    const currentResult = result;
    if (!currentResult) {
      return;
    }
    // Synchronous ref guard: `disabled` only takes effect on the next commit, so a
    // fast double-click would otherwise slip a duplicate audit event through.
    if (adjudicationBusyRowIdsRef.current.has(rowId)) {
      return;
    }
    const taskId = currentResult.task_id;
    adjudicationBusyRowIdsRef.current = new Set(adjudicationBusyRowIdsRef.current).add(rowId);
    setAdjudicationBusyRowIds(adjudicationBusyRowIdsRef.current);
    setAdjudicationError(null);
    try {
      await submitNetworkAdjudication(taskId, {
        lineage_row_id: rowId,
        decision,
        reason,
      });
    } catch (error) {
      if (mountedRef.current && activeTaskIdRef.current === taskId) {
        setAdjudicationError(describeApiError(error, "提交人工判定"));
      }
      releaseAdjudicationRow(rowId);
      return;
    }
    // The write landed. A failed refresh must not be reported as a failed decision.
    try {
      const refreshed = await fetchNetworkResult(taskId);
      if (!mountedRef.current || activeTaskIdRef.current !== taskId) {
        return;
      }
      if (refreshed.result) {
        setResult(refreshed.result);
      }
      setAdjudication(refreshed.adjudication ?? null);
      setAssemblyGate(refreshed.assembly_gate ?? null);
    } catch {
      if (mountedRef.current && activeTaskIdRef.current === taskId) {
        setAdjudicationError("人工判定已记录，但刷新判定进度失败；请重新加载任务以查看最新状态。");
      }
    } finally {
      releaseAdjudicationRow(rowId);
    }
  }

  async function onSealAssemblyPlan() {
    const currentResult = result;
    if (!currentResult || assemblyPlanBusy) {
      return;
    }
    const taskId = currentResult.task_id;
    setAssemblyPlanBusy(true);
    setAssemblyPlanError(null);
    try {
      await sealNetworkAssemblyPlan(taskId);
    } catch (error) {
      if (mountedRef.current && activeTaskIdRef.current === taskId) {
        setAssemblyPlanError(error instanceof ApiStatusError && error.status === 422
          ? "装配输入仍被门禁阻塞；请完成全部逐行判定，并保留至少一条有双侧纳入依据的交集。"
          : describeApiError(error, "封存候选装配输入"));
      }
      setAssemblyPlanBusy(false);
      return;
    }
    try {
      const refreshed = await fetchNetworkResult(taskId);
      if (!mountedRef.current || activeTaskIdRef.current !== taskId) {
        return;
      }
      if (refreshed.result) {
        setResult(refreshed.result);
      }
      setAdjudication(refreshed.adjudication ?? null);
      setAssemblyGate(refreshed.assembly_gate ?? null);
    } catch {
      if (mountedRef.current && activeTaskIdRef.current === taskId) {
        setAssemblyPlanError("装配输入已封存，但刷新门禁状态失败；请重新加载任务查看最新计划。");
      }
    } finally {
      if (mountedRef.current) {
        setAssemblyPlanBusy(false);
      }
    }
  }

  function releaseAdjudicationRow(rowId: string) {
    const next = new Set(adjudicationBusyRowIdsRef.current);
    next.delete(rowId);
    adjudicationBusyRowIdsRef.current = next;
    if (mountedRef.current) {
      setAdjudicationBusyRowIds(next);
    }
  }

  useEffect(() => {
    if (!taskIdParam) {
      return;
    }
    if (appliedTaskIdRef.current === taskIdParam) {
      return;
    }
    appliedTaskIdRef.current = taskIdParam;
    beginRun();
    setPhase("polling");
    void pollUntilCompleted(taskIdParam);
    // one-shot deep link from 我的研究: depend only on taskIdParam so re-renders do not re-poll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskIdParam]);

  useEffect(() => {
    if (!focusEntityId) {
      return;
    }
    if (taskIdParam) {
      return;
    }
    if (appliedFocusRef.current === focusEntityId) {
      return;
    }
    appliedFocusRef.current = focusEntityId;

    // focus 深链只做预填，绝不自动运行：分析任务是显式的写操作，
    // 点一个实体 chip 不应该静默创建任务，离开页面也不会留下卡在 running 的任务。
    fetchNetworkEntities()
      .then((lookup) => {
        if (!mountedRef.current) {
          return;
        }
        const entity: NetworkEntity | undefined = lookup[focusEntityId];
        if (!entity) {
          setInfoMessage(`未在网药实体字典中找到「${focusEntityId}」，请直接输入方药名称。`);
          return;
        }
        if (entity.kind === "herb" || entity.kind === "formula") {
          setQuery(entity.name);
          setAnalysisType(entity.kind);
          setInfoMessage(
            `已按实体预填分析对象「${entity.name}」（${getEntityKindLabel(entity.kind)}），请核对研究协议后点击开始分析。`,
          );
          return;
        }
        setInfoMessage(
          `「${entity.name}」是${getEntityKindLabel(entity.kind)}，不作为分析对象；可用链路卡的「查相关文献」「去 RAG 提问」继续。`,
        );
      })
      .catch(() => {
        if (!mountedRef.current) {
          return;
        }
        setErrorMessage("加载网药实体失败，无法解析 focus 参数。");
        setPhase("error");
      });
    // one-shot prefill: depend only on focusEntityId so re-renders do not re-apply.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusEntityId]);

  const isBusy = phase === "submitting" || phase === "polling";
  const submitLabel = isBusy
    ? phase === "submitting"
      ? "提交中..."
      : `运行中... ${progress}%`
    : "开始分析";
  const resultDataMode = result?.data_mode ?? "mock";

  async function runOmicsVerification(event: FormEvent) {
    event.preventDefault();
    const taskId = result?.task_id;
    const accession = omicsAccession.trim();
    if (!taskId || !accession) return;
    setOmicsBusy(true);
    setOmicsMessage(null);
    setOmicsSummary(null);
    try {
      const payload = await fetchNetworkOmicsVerification(taskId, accession);
      const projection = payload.omics_verification;
      if (!projection) {
        setOmicsMessage("后端未返回组学投影（任务可能尚未完成），请稍后重试。");
        return;
      }
      setOmicsSummary(
        `快照 ${projection.accession}（${projection.comparison}）：${getNetworkOmicsVerificationSummary(projection)}`,
      );
    } catch (error) {
      if (error instanceof ApiStatusError) {
        if (error.status === 404) {
          setOmicsMessage(`未找到 ${accession} 对应的组学快照：请先完成组学导入核验（快照冻结）再试。`);
        } else if (error.status === 409) {
          setOmicsMessage("组学验证需要一个已完成的分析任务，请等当前任务跑完再试。");
        } else if (error.status === 422) {
          setOmicsMessage("组学核验未通过或参数不完整（快照未通过核验/登录号格式不合法），请核对导入核验记录。");
        } else {
          setOmicsMessage(`组学验证请求失败（HTTP ${error.status}）。`);
        }
      } else {
        setOmicsMessage(error instanceof Error ? error.message : "组学验证请求失败。");
      }
    } finally {
      setOmicsBusy(false);
    }
  }
  const isLiveResult = resultDataMode === "live";
  const isImportedSnapshotResult =
    Boolean(result?.source_task_id) || Boolean(result?.target_lineage.compound_import_provenance);
  const visibleChains = isImportedSnapshotResult ? [] : result?.chains ?? [];
  const isProviderNetworkResult = isLiveResult && !isImportedSnapshotResult;
  const verifiedDiseaseProvenance =
    result?.target_lineage.disease_import_provenance?.provenance_verification_status ===
    "server_verified_raw_artifact";
  const adjudicationDecisionMap = buildNetworkAdjudicationDecisionMap(adjudication?.current);
  const adjudicationCounts = adjudication?.counts ?? null;
  const adjudicationRowCount = result ? countNetworkLineageRows(result.target_lineage) : 0;
  const adjudicationUnavailableReason = getNetworkAdjudicationUnavailableReason({
    taskCompleted: phase === "completed" && Boolean(result),
    lineageRowCount: adjudicationRowCount,
  });
  const adjudicationInFlightMessage = getNetworkAdjudicationInFlightMessage(
    adjudicationBusyRowIds.size,
  );
  const rowAdjudicationControls: RowAdjudicationControls = {
    enabled: adjudicationUnavailableReason === null,
    busyRowIds: adjudicationBusyRowIds,
    decisionMap: adjudicationDecisionMap,
    onSubmit: (rowId, decision, reason) => {
      void onSubmitAdjudication(rowId, decision, reason);
    },
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section style={getSurfaceSectionStyle()}>
        <div style={{ display: "grid", gap: 8, marginBottom: 20 }}>
          <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>研究对象与协议</h2>
          <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}>
            先冻结研究对象、明确 AD 表型、物种、证据策略和查询日期，再运行可审计的网络药理学任务。
          </p>
        </div>

        {infoMessage ? (
          <div style={{ marginBottom: 16 }}>
            <StatusPanel message={infoMessage} />
          </div>
        ) : null}

        <form onSubmit={onSubmit} style={{ display: "grid", gap: 16 }}>
          <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
            分析对象
            <input
              name="query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-label="机制线索分析对象"
              maxLength={NETWORK_QUERY_MAX_LENGTH}
              style={{
                width: "100%",
                border: "1px solid var(--qiyan-line)",
                borderRadius: 8,
                fontSize: 16,
                padding: "12px 14px",
              }}
            />
          </label>

          <div style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap" }}>
            <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
              对象类型
              <select
                name="analysis_type"
                value={analysisType}
                onChange={(event) => setAnalysisType(event.target.value as NetworkAnalysisType)}
                aria-label="机制线索对象类型"
                style={{
                  minWidth: 180,
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  fontSize: 16,
                  padding: "12px 14px",
                }}
              >
                <option value="formula">复方</option>
                <option value="herb">单味中药</option>
              </select>
            </label>

          </div>

          <fieldset
            style={{
              display: "grid",
              gap: 16,
              margin: 0,
              padding: 16,
              border: "1px solid var(--qiyan-line)",
              borderRadius: 8,
              background: "var(--qiyan-surface-3)",
            }}
          >
            <legend style={{ padding: "0 8px", color: "var(--qiyan-ink)", fontWeight: 800 }}>
              研究协议（运行前冻结）
            </legend>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
              <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                疾病范围
                <input value="特应性皮炎（AD）" readOnly style={{ border: "1px solid var(--qiyan-line)", borderRadius: 8, padding: "12px 14px", fontSize: 16 }} />
              </label>
              <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                研究物种
                <input value="Homo sapiens" readOnly style={{ border: "1px solid var(--qiyan-line)", borderRadius: 8, padding: "12px 14px", fontSize: 16 }} />
              </label>
              <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                证据策略
                <select
                  value={evidencePolicy}
                  onChange={(event) => setEvidencePolicy(event.target.value as NetworkEvidencePolicy)}
                  aria-label="网络药理学证据策略"
                  style={{ border: "1px solid var(--qiyan-line)", borderRadius: 8, padding: "12px 14px", fontSize: 16 }}
                >
                  <option value="direct_human_first">直接人类证据优先</option>
                  <option value="mixed_exploratory">混合探索（含预测关联）</option>
                </select>
              </label>
              <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                查询日期
                <input
                  type="date"
                  value={queryDate}
                  max={toLocalDateInputValue(new Date())}
                  onChange={(event) => setQueryDate(event.target.value)}
                  aria-label="网络药理学查询日期"
                  style={{ border: "1px solid var(--qiyan-line)", borderRadius: 8, padding: "12px 14px", fontSize: 16 }}
                />
              </label>
            </div>
            <label style={{ display: "grid", gap: 8, color: "var(--qiyan-ink)", fontWeight: 700 }}>
              明确研究表型
              <input
                value={phenotype}
                onChange={(event) => setPhenotype(event.target.value)}
                aria-label="特应性皮炎研究表型"
                style={{ border: "1px solid var(--qiyan-line)", borderRadius: 8, padding: "12px 14px", fontSize: 16 }}
              />
              <span style={{ color: "var(--qiyan-muted)", fontSize: 13, fontWeight: 500 }}>
                禁止只使用宽泛 disease target union；请写明本次研究关注的 AD 表型或机制边界。
              </span>
            </label>
            <div
              style={{
                borderTop: "1px solid var(--qiyan-line)",
                paddingTop: 16,
                display: "grid",
                gap: 10,
              }}
            >
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <strong style={{ color: "var(--qiyan-ink)" }}>Open Targets 原始疾病关联导出</strong>
                <input
                  ref={diseaseImportInputRef}
                  type="file"
                  accept=".json,application/json"
                  onChange={onDiseaseImportChange}
                  aria-label="选择 Open Targets 原始导出文件"
                  style={{ display: "none" }}
                />
                <button
                  type="button"
                  onClick={() => diseaseImportInputRef.current?.click()}
                  disabled={isBusy}
                  style={{
                    border: "1px solid var(--qiyan-line)",
                    borderRadius: 8,
                    background: "var(--qiyan-surface)",
                    color: "var(--qiyan-ink)",
                    minHeight: 40,
                    padding: "8px 12px",
                    fontWeight: 700,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <UploadOutlined aria-hidden />
                  选择原始文件
                </button>
                {diseaseRawArtifact ? (
                  <button
                    type="button"
                    onClick={removeDiseaseImport}
                    disabled={isBusy}
                    aria-label="移除疾病靶点 artifact"
                    title="移除疾病靶点 artifact"
                    style={{
                      width: 40,
                      height: 40,
                      border: "1px solid var(--qiyan-line)",
                      borderRadius: 8,
                      background: "var(--qiyan-surface)",
                      color: "var(--qiyan-muted-2)",
                    }}
                  >
                    <CloseOutlined aria-hidden />
                  </button>
                ) : null}
              </div>
              {diseaseRawArtifact ? (
                <div
                  role="status"
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                    gap: 8,
                    color: "var(--qiyan-muted-2)",
                    fontSize: 13,
                  }}
                >
                  <span>文件：{diseaseImportFileName}</span>
                  <span>提交方式：multipart 原始字节</span>
                  <span>核验边界：服务端 SHA-256 + 服务端解析</span>
                </div>
              ) : (
                <span style={{ color: "var(--qiyan-muted)", fontSize: 13 }}>未导入</span>
              )}
              <details
                aria-label="部署方高级配置（operator）"
                style={{
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  background: "var(--qiyan-surface)",
                  padding: "10px 12px",
                }}
              >
                <summary style={{ cursor: "pointer", color: "var(--qiyan-ink)", fontWeight: 700 }}>
                  部署方高级配置（operator）
                </summary>
                <p style={{ color: "var(--qiyan-muted)", fontSize: 13, margin: "8px 0 12px", lineHeight: 1.6 }}>
                  以下字段由部署方按数据来源与合规要求冻结，普通使用无需修改；改动会进入服务端核验的导入声明。
                </p>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
                <label style={{ display: "grid", gap: 6, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                  Open Targets release
                  <input value={openTargetsRelease} onChange={(event) => setOpenTargetsRelease(event.target.value)} />
                </label>
                <label style={{ display: "grid", gap: 6, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                  关联分数阈值
                  <input value={diseaseThreshold} onChange={(event) => setDiseaseThreshold(event.target.value)} inputMode="decimal" />
                </label>
                <label style={{ display: "grid", gap: 6, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                  Identifier mapping version
                  <input value={identifierMappingVersion} onChange={(event) => setIdentifierMappingVersion(event.target.value)} />
                </label>
                <label style={{ display: "grid", gap: 6, color: "var(--qiyan-ink)", fontWeight: 700 }}>
                  retrieved_at
                  <input value={retrievedAt} onChange={(event) => setRetrievedAt(event.target.value)} />
                </label>
                <label style={{ display: "grid", gap: 6, color: "var(--qiyan-ink)", fontWeight: 700, gridColumn: "1 / -1" }}>
                  Usage / license note
                  <input value={usageLicenseNote} onChange={(event) => setUsageLicenseNote(event.target.value)} />
                </label>
                </div>
              </details>
              <span style={{ color: "var(--qiyan-muted)", fontSize: 13, lineHeight: 1.6 }}>
                选择原始文件后，运行任务将由服务端核验 release、阈值与映射声明；客户端不提交 records、hash 或判定字段。
              </span>
            </div>
          </fieldset>

          <div>
            <button
              type="submit"
              disabled={isBusy}
              style={{
                border: 0,
                borderRadius: 8,
                background: isBusy ? "#94a3b8" : "#0d9488",
                color: "white",
                fontSize: 16,
                fontWeight: 700,
                padding: "12px 20px",
                minHeight: 44,
              }}
            >
              {submitLabel}
            </button>
          </div>
        </form>
      </section>

      {phase === "error" && errorMessage ? (
        <div style={{ display: "grid", gap: 10 }}>
          <StatusPanel message={errorMessage} tone="error" />
          {errorHint ? (
            <a
              href={errorHint.href}
              style={{ color: "#0d9488", fontWeight: 700, width: "fit-content" }}
            >
              {errorHint.label}
            </a>
          ) : null}
        </div>
      ) : null}

      {phase === "completed" && result ? (
        <section style={getSurfaceSectionStyle()}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 16,
              alignItems: "start",
              flexWrap: "wrap",
              marginBottom: 16,
            }}
          >
            <div style={{ display: "grid", gap: 4, flex: "1 1 560px" }}>
              <h2 style={{ color: "var(--qiyan-ink)", fontSize: 24, margin: 0 }}>
                {isImportedSnapshotResult ? "冻结靶点快照与派生交集" : "「成分-靶点-通路-疾病」链"}
              </h2>
              <p
                title={result.query}
                style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.6 }}
              >
                {isImportedSnapshotResult
                  ? `分析对象 ${truncateLabel(result.query)}（${getNetworkAnalysisTypeLabel(result.analysis_type)}）。当前仅展示冻结 lineage 与服务端派生交集；未构建 provider chains、PPI、pathway 或 enrichment。`
                  : `分析对象 ${truncateLabel(result.query)}（${getNetworkAnalysisTypeLabel(result.analysis_type)}）共返回 ${visibleChains.length} 条链；分数为${isLiveResult ? "来源置信度或预测分数，需核对下方数据来源与缓存状态。" : "mock 置信度，仅用于 UI 演示。"}`}
              </p>
            </div>
            <button
              type="button"
              onClick={onDownloadReport}
              aria-label="导出报告为 Markdown"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 8,
                border: "1px solid #0d9488",
                borderRadius: 8,
                background: "var(--qiyan-surface)",
                color: "#0f766e",
                fontSize: 14,
                fontWeight: 700,
                padding: "10px 14px",
                minHeight: 44,
                cursor: "pointer",
              }}
            >
              <DownloadOutlined aria-hidden="true" />
              <span>导出报告为 Markdown</span>
            </button>
          </div>
          {isImportedSnapshotResult ? (
            <div
              aria-label="冻结靶点快照边界"
              style={{
                border: "1px solid rgba(180, 83, 9, 0.28)",
                borderRadius: 8,
                background: "rgba(255, 251, 235, 0.78)",
                padding: "12px 14px",
                marginBottom: 16,
                color: "var(--qiyan-ink)",
                lineHeight: 1.6,
              }}
            >
              <strong>冻结靶点快照（非完整网络）</strong>
              <span style={{ color: "var(--qiyan-muted-2)" }}>
                ：仅展示冻结 lineage 与服务端派生交集；未构建 provider chains、PPI、pathway 或 enrichment。即使数据模式为真实数据 opt-in，也不表示 provider 网络已运行。
              </span>
            </div>
          ) : isLiveResult ? (
            <div
              aria-label="真实数据 opt-in 状态"
              style={{
                border: "1px solid rgba(13, 148, 136, 0.28)",
                borderRadius: 8,
                background: "rgba(240, 253, 250, 0.76)",
                padding: "12px 14px",
                marginBottom: 16,
                color: "var(--qiyan-ink)",
                lineHeight: 1.6,
              }}
            >
              <strong>{getNetworkDataModeLabel(resultDataMode)}</strong>
              <span style={{ color: "var(--qiyan-muted-2)" }}>
                ：结果来自显式启用的真实数据链路，包含缓存或导入来源；预测靶点不会自动爬取 SwissTargetPrediction。
              </span>
            </div>
          ) : null}
          <section
            aria-label="科研就绪门禁"
            style={{
              border: "1px solid rgba(180, 83, 9, 0.28)",
              borderRadius: 8,
              background: "rgba(255, 251, 235, 0.78)",
              padding: "14px 16px",
              marginBottom: 20,
            }}
          >
            <h3 style={{ color: "var(--qiyan-ink)", fontSize: 18, margin: "0 0 8px" }}>科研就绪门禁</h3>
            <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 8px", lineHeight: 1.65 }}>
              formal_network_ready：
              {result.readiness?.formal_network_ready ? "是（达到正式科研标准）" : "否（未达正式科研标准）"}
              ；协议完整：
              {result.readiness?.protocol_complete ? "是" : "否"}。
            </p>
            {result.research_protocol ? (
              <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 8px", lineHeight: 1.65 }}>
                表型：{result.research_protocol.phenotype} · 物种：{result.research_protocol.species} · 查询日期：
                {result.research_protocol.query_date}
              </p>
            ) : null}
            <ul style={{ margin: 0, paddingLeft: 20, color: "var(--qiyan-muted-2)", lineHeight: 1.65 }}>
              {(result.readiness?.blocking_reasons ?? ["缺少可审计的研究协议。"]).map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </section>
          <section
            aria-label="靶点集合与逐行 Lineage"
            style={{
              border: "1px solid var(--qiyan-line)",
              borderRadius: 8,
              background: "var(--qiyan-surface)",
              padding: "16px",
              marginBottom: 24,
            }}
          >
            <div style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <h3 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: 0 }}>
                靶点集合与逐行 Lineage
              </h3>
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.65 }}>
                疾病与成分靶点必须来自独立上游证据集合；交集只能由两者派生，自动抽取记录在人工判定前不得升级为正式研究事实。
              </p>
            </div>

            <div
              aria-label="人工判定进度"
              style={{
                border: "1px solid var(--qiyan-line)",
                borderRadius: 8,
                background: "var(--qiyan-surface-3)",
                padding: "12px 14px",
                marginBottom: 16,
                display: "grid",
                gap: 8,
              }}
            >
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                <strong style={{ color: "var(--qiyan-ink)" }}>人工判定</strong>
                <span style={{ color: "var(--qiyan-muted-2)", fontSize: 14 }}>
                  已纳入 {adjudicationCounts?.included ?? 0} · 已排除 {adjudicationCounts?.excluded ?? 0} ·
                  待复核 {adjudicationCounts?.needs_review ?? 0} · 未判定{" "}
                  {adjudicationCounts?.pending ?? adjudicationRowCount}
                </span>
              </div>
              <p style={{ color: "var(--qiyan-muted)", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                人工判定仅记录 reviewer 决策，不会修改快照数据，也不会单独使网络达到正式科研标准。
              </p>
              {adjudicationUnavailableReason ? (
                <p role="note" style={{ color: "#92400e", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                  {adjudicationUnavailableReason}
                </p>
              ) : null}
              <p
                role="status"
                aria-live="polite"
                style={{ color: "var(--qiyan-muted-2)", fontSize: 13, margin: 0, lineHeight: 1.6 }}
              >
                {adjudicationInFlightMessage ?? ""}
              </p>
              {adjudicationError ? (
                <p role="alert" style={{ color: "#b91c1c", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                  {adjudicationError}
                </p>
              ) : null}
            </div>

            {isImportedSnapshotResult ? (
              <div
                aria-label="候选装配输入门禁"
                style={{
                  border: "1px solid var(--qiyan-line)",
                  borderRadius: 8,
                  background: "var(--qiyan-surface-3)",
                  padding: "12px 14px",
                  marginBottom: 16,
                  display: "grid",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                  <strong style={{ color: "var(--qiyan-ink)" }}>候选装配输入</strong>
                  <span style={{ color: "var(--qiyan-muted-2)", fontSize: 14 }}>
                    {assemblyGate?.state === "assembly_input_ready" ? "已封存" : "仍被门禁阻塞"}
                  </span>
                </div>
                <p style={{ color: "var(--qiyan-muted)", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                  封存只绑定当前协议、双侧 artifact、冻结 lineage 与 latest-wins 判定快照；不生成网络边，不授权后续 writer，也不翻转 formal_network_ready。
                </p>
                {assemblyGate?.blockers.length ? (
                  <ul style={{ margin: 0, paddingLeft: 20, color: "#92400e", fontSize: 13, lineHeight: 1.6 }}>
                    {assemblyGate.blockers.map((blocker) => (
                      <li key={`${blocker.code}-${blocker.row_ids.join("-")}`}>
                        {getAssemblyGateBlockerLabel(blocker.code)}
                        {blocker.row_ids.length ? `（${blocker.row_ids.length} 行）` : ""}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {assemblyGate?.latest_plan ? (
                  <p style={{ color: "var(--qiyan-muted-2)", fontSize: 13, margin: 0, overflowWrap: "anywhere" }}>
                    最新计划：{assemblyGate.latest_plan.plan_id} · 纳入交集 {assemblyGate.latest_plan.selected_intersection_count}
                    {assemblyGate.latest_plan.is_consumed ? " · 已被 writer 消费（审计记录）" : " · 尚未消费"}
                  </p>
                ) : null}
                <div>
                  <button
                    type="button"
                    onClick={onSealAssemblyPlan}
                    disabled={assemblyPlanBusy}
                    aria-label="封存候选装配输入"
                    style={{
                      border: "1px solid #0d9488",
                      borderRadius: 8,
                      background: assemblyPlanBusy ? "var(--qiyan-surface-3)" : "var(--qiyan-surface)",
                      color: "#0f766e",
                      fontSize: 13,
                      fontWeight: 700,
                      minHeight: 40,
                      padding: "8px 12px",
                    }}
                  >
                    {assemblyPlanBusy ? "封存中..." : "封存候选装配输入"}
                  </button>
                </div>
                {assemblyPlanError ? (
                  <p role="alert" style={{ color: "#b91c1c", fontSize: 13, margin: 0, lineHeight: 1.6 }}>
                    {assemblyPlanError}
                  </p>
                ) : null}
              </div>
            ) : null}

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                gap: 12,
                marginBottom: 16,
              }}
            >
              {[
                ["疾病靶点", result.target_lineage.disease_target_count],
                ["成分靶点", result.target_lineage.compound_target_count],
                ["派生候选交集", result.target_lineage.intersection_target_count],
                [
                  "Source lineage 行",
                  result.target_lineage.disease_lineage_row_count +
                    result.target_lineage.compound_lineage_row_count,
                ],
              ].map(([label, value]) => (
                <div
                  key={String(label)}
                  style={{
                    border: "1px solid var(--qiyan-line)",
                    borderRadius: 8,
                    background: "var(--qiyan-surface-3)",
                    padding: "12px 14px",
                  }}
                >
                  <span style={{ color: "var(--qiyan-muted)", fontSize: 13 }}>{label}</span>
                  <strong style={{ display: "block", color: "var(--qiyan-ink)", fontSize: 22, marginTop: 4 }}>
                    {value}
                  </strong>
                </div>
              ))}
            </div>

            {result.target_lineage.disease_import_provenance ? (
              <div
                role="note"
                aria-label="疾病靶点导入来源"
                style={{
                  borderTop: "1px solid var(--qiyan-line)",
                  borderBottom: "1px solid var(--qiyan-line)",
                  padding: "12px 0",
                  marginBottom: 16,
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 8,
                  color: "var(--qiyan-muted-2)",
                  fontSize: 13,
                }}
              >
                <span>
                  来源：{result.target_lineage.disease_import_provenance.source_database} /{" "}
                  {result.target_lineage.disease_import_provenance.database_version}
                </span>
                <span>
                  查询：{result.target_lineage.disease_import_provenance.source_query_id} /{" "}
                  {result.target_lineage.disease_import_provenance.source_query_label}
                </span>
                <span>
                  阈值：{result.target_lineage.disease_import_provenance.score_name} {" "}
                  {result.target_lineage.disease_import_provenance.threshold_operator} {" "}
                  {formatScore(result.target_lineage.disease_import_provenance.applied_threshold)}
                </span>
                <span>
                  记录：{result.target_lineage.disease_import_provenance.record_count} / 状态：
                  {result.target_lineage.disease_import_provenance.provenance_verification_status}
                </span>
                {result.target_lineage.disease_import_provenance.provenance_verification_status ===
                "server_verified_raw_artifact" ? (
                  <strong
                    style={{
                      color: "#0f766e",
                      background: "rgba(204, 251, 241, 0.72)",
                      border: "1px solid rgba(13, 148, 136, 0.3)",
                      borderRadius: 999,
                      padding: "3px 10px",
                      justifySelf: "start",
                    }}
                  >
                    服务端原始文件核验
                  </strong>
                ) : (
                  <strong style={{ color: "#92400e" }}>未验证客户端导入</strong>
                )}
                <span style={{ gridColumn: "1 / -1", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                  Import SHA-256：
                  {result.target_lineage.disease_import_provenance.import_payload_sha256}
                </span>
                {result.target_lineage.disease_import_provenance.source_artifact_sha256 ? (
                  <span style={{ gridColumn: "1 / -1", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                    Source artifact SHA-256：
                    {result.target_lineage.disease_import_provenance.source_artifact_sha256}
                  </span>
                ) : null}
                {result.target_lineage.disease_import_provenance.usage_license_note ? (
                  <span style={{ gridColumn: "1 / -1" }}>
                    Usage / license note：
                    {result.target_lineage.disease_import_provenance.usage_license_note}
                  </span>
                ) : null}
                <span style={{ gridColumn: "1 / -1", color: "#92400e" }}>
                  {result.target_lineage.disease_import_provenance.provenance_verification_status ===
                  "server_verified_raw_artifact"
                    ? "source_artifact_sha256 只证明原始字节完整性与服务端解析一致性，不证明 release 选择正确或靶点具有生物学意义。"
                    : "unverified_client_import：payload 哈希只证明导入内容完整性，不证明外部来源真实性。"}
                </span>
              </div>
            ) : null}

            {result.target_lineage.compound_import_provenance ? (
              <div
                role="note"
                aria-label="成分靶点导入来源"
                style={{
                  borderBottom: "1px solid var(--qiyan-line)",
                  padding: "0 0 12px",
                  marginBottom: 16,
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                  gap: 8,
                  color: "var(--qiyan-muted-2)",
                  fontSize: 13,
                }}
              >
                <span>
                  Compound：{result.target_lineage.compound_import_provenance.compound_id} /{" "}
                  {result.target_lineage.compound_import_provenance.compound_label}
                </span>
                <span>
                  来源：{result.target_lineage.compound_import_provenance.source_database} /{" "}
                  {result.target_lineage.compound_import_provenance.database_version}
                </span>
                <span>
                  阈值：{result.target_lineage.compound_import_provenance.score_name} {" "}
                  {result.target_lineage.compound_import_provenance.threshold_operator} {" "}
                  {result.target_lineage.compound_import_provenance.applied_threshold}
                </span>
                <span>
                  记录：{result.target_lineage.compound_import_provenance.record_count} / 状态：
                  {result.target_lineage.compound_import_provenance.provenance_verification_status}
                </span>
                {result.source_task_id ? (
                  <span style={{ gridColumn: "1 / -1", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                    父疾病任务引用：{result.source_task_id}
                  </span>
                ) : null}
                <span style={{ gridColumn: "1 / -1", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                  Import SHA-256：{result.target_lineage.compound_import_provenance.import_payload_sha256}
                </span>
                <span style={{ gridColumn: "1 / -1", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                  Source artifact SHA-256：
                  {result.target_lineage.compound_import_provenance.source_artifact_sha256}
                </span>
                <span style={{ gridColumn: "1 / -1" }}>
                  Usage / license note：
                  {result.target_lineage.compound_import_provenance.usage_license_note}
                </span>
                <strong style={{ gridColumn: "1 / -1", color: "#92400e" }}>
                  server_verified_raw_artifact 仅为中间态，formal_network_ready=false；字节一致性不证明
                  compound-target 边具有生物学意义。
                </strong>
              </div>
            ) : verifiedDiseaseProvenance ? (
              <form
                onSubmit={onSubmitCompoundImport}
                aria-label="成分靶点原始 artifact"
                style={{
                  borderBottom: "1px solid var(--qiyan-line)",
                  padding: "0 0 16px",
                  marginBottom: 16,
                  display: "grid",
                  gap: 12,
                }}
              >
                <fieldset disabled={isBusy}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <input
                    ref={compoundImportInputRef}
                    type="file"
                    accept=".json,application/json"
                    aria-label="选择 ChEMBL 成分靶点原始文件"
                    onChange={onCompoundImportChange}
                    style={{ display: "none" }}
                  />
                  <button
                    type="button"
                    onClick={() => compoundImportInputRef.current?.click()}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      border: "1px solid #0d9488",
                      borderRadius: 8,
                      background: "var(--qiyan-surface)",
                      color: "#0f766e",
                      padding: "9px 12px",
                      minHeight: 40,
                      fontWeight: 700,
                    }}
                  >
                    <UploadOutlined aria-hidden="true" />
                    <span>选择 ChEMBL 原始文件</span>
                  </button>
                  <span style={{ color: "var(--qiyan-muted-2)", overflowWrap: "anywhere" }}>
                    {compoundImportFileName ?? "未选择文件"}
                  </span>
                  {compoundRawArtifact ? (
                    <button
                      type="button"
                      onClick={removeCompoundImport}
                      aria-label="移除 ChEMBL 原始文件"
                      title="移除 ChEMBL 原始文件"
                      style={{ border: 0, background: "transparent", color: "#92400e", padding: 6 }}
                    >
                      <CloseOutlined aria-hidden="true" />
                    </button>
                  ) : null}
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
                    gap: 12,
                  }}
                >
                  <label style={{ display: "grid", gap: 6 }}>
                    ChEMBL compound ID
                    <input value={chemblCompoundId} onChange={(event) => setChemblCompoundId(event.target.value)} />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    Compound label
                    <input value={chemblCompoundLabel} onChange={(event) => setChemblCompoundLabel(event.target.value)} />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    ChEMBL release
                    <input value={chemblRelease} onChange={(event) => setChemblRelease(event.target.value)} />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    pChEMBL threshold
                    <input value={chemblThreshold} onChange={(event) => setChemblThreshold(event.target.value)} inputMode="decimal" />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    Mapping version
                    <input value={chemblMappingVersion} onChange={(event) => setChemblMappingVersion(event.target.value)} />
                  </label>
                  <label style={{ display: "grid", gap: 6 }}>
                    Retrieved at（ISO 8601）
                    <input value={chemblRetrievedAt} onChange={(event) => setChemblRetrievedAt(event.target.value)} />
                  </label>
                  <label style={{ display: "grid", gap: 6, gridColumn: "1 / -1" }}>
                    Usage / license note
                    <input value={chemblUsageLicenseNote} onChange={(event) => setChemblUsageLicenseNote(event.target.value)} />
                  </label>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <button
                    type="submit"
                    disabled={!compoundRawArtifact || isBusy}
                    style={{
                      border: 0,
                      borderRadius: 8,
                      background: compoundRawArtifact && !isBusy ? "#0d9488" : "#94a3b8",
                      color: "white",
                      fontWeight: 700,
                      padding: "10px 14px",
                      minHeight: 40,
                    }}
                  >
                    服务端核验成分 artifact
                  </button>
                  <span style={{ color: "#92400e", fontSize: 13 }}>
                    source task：{result.task_id}；客户端不提交 records、hash、owner 或判定字段。
                  </span>
                </div>
                </fieldset>
              </form>
            ) : (
              <div role="note" aria-label="成分靶点原始 artifact 状态" style={{ color: "var(--qiyan-muted-2)", marginBottom: 16 }}>
                需先完成服务端核验的疾病靶点任务，才能创建 owner-scoped 成分靶点派生任务。
              </div>
            )}

            {result.target_lineage.warnings.length > 0 ? (
              <ul style={{ color: "#92400e", lineHeight: 1.65, margin: "0 0 16px", paddingLeft: 20 }}>
                {result.target_lineage.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}

            <h4 style={{ color: "var(--qiyan-ink)", fontSize: 16, margin: "0 0 8px" }}>疾病靶点集合</h4>
            {result.target_lineage.disease_targets.length === 0 ? (
              <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 16px", lineHeight: 1.65 }}>
                {verifiedDiseaseProvenance
                  ? "服务端核验的疾病靶点 artifact 在当前阈值下零命中；疾病集合与派生交集保持空集。"
                  : result.target_lineage.disease_import_provenance
                  ? "客户端导入声明零命中；来源与查询执行尚未由服务端验证。"
                  : "未采集独立疾病靶点集合；当前不能计算疾病-成分靶点交集。"}
              </p>
            ) : (
              <TargetLineageTable
                rows={result.target_lineage.disease_targets}
                adjudication={rowAdjudicationControls}
              />
            )}

            <h4 style={{ color: "var(--qiyan-ink)", fontSize: 16, margin: "0 0 8px" }}>成分靶点逐行记录</h4>
            {result.target_lineage.compound_targets.length === 0 ? (
              <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 16px" }}>未提取成分靶点。</p>
            ) : (
              <TargetLineageTable
                rows={result.target_lineage.compound_targets}
                adjudication={rowAdjudicationControls}
              />
            )}

            <h4 style={{ color: "var(--qiyan-ink)", fontSize: 16, margin: "0 0 8px" }}>
              派生候选交集
            </h4>
            {result.target_lineage.intersection_targets.length === 0 ? (
              <p style={{ color: "var(--qiyan-muted-2)", margin: 0, lineHeight: 1.65 }}>
                当前没有服务端派生的候选交集；禁止从成分靶点集合自我构造疾病交集。
              </p>
            ) : (
              <div style={{ maxWidth: "100%", overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    minWidth: 1360,
                    borderCollapse: "collapse",
                    fontSize: 13,
                    textAlign: "left",
                  }}
                >
                  <thead>
                    <tr style={{ borderBottom: "2px solid var(--qiyan-line)" }}>
                      {[
                        "Derivation row ID",
                        "标准符号",
                        "派生规则",
                        "疾病 lineage refs",
                        "成分 lineage refs",
                        "自动状态",
                        "人工判定",
                        "决策",
                        "Reviewer 判定操作",
                      ].map((heading) => (
                        <th
                          key={heading}
                          scope="col"
                          style={{ padding: "10px 8px", color: "var(--qiyan-muted)", whiteSpace: "nowrap" }}
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.target_lineage.intersection_targets.map((row) => (
                      <tr key={row.lineage_row_id} style={{ borderBottom: "1px solid var(--qiyan-line)" }}>
                        <td style={{ padding: "10px 8px", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                          {row.lineage_row_id}
                        </td>
                        <td style={{ padding: "10px 8px", color: "var(--qiyan-ink)", fontWeight: 800 }}>
                          {row.canonical_symbol}
                        </td>
                        <td style={{ padding: "10px 8px" }}>{row.derivation}</td>
                        <td style={{ padding: "10px 8px", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                          {row.disease_lineage_row_ids.join(", ")}
                        </td>
                        <td style={{ padding: "10px 8px", fontFamily: "monospace", overflowWrap: "anywhere" }}>
                          {row.compound_lineage_row_ids.join(", ")}
                        </td>
                        <td style={{ padding: "10px 8px" }}>{row.automatic_status}</td>
                        <td style={{ padding: "10px 8px", color: "#92400e", fontWeight: 700 }}>
                          {row.adjudication_status}
                        </td>
                        <td style={{ padding: "10px 8px" }}>{row.decision}</td>
                        <td style={{ padding: "10px 8px", verticalAlign: "top" }}>
                          <LineageAdjudicationCell
                            rowId={row.lineage_row_id}
                            controls={rowAdjudicationControls}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <NetworkGraph
            chains={visibleChains}
            taskId={result.task_id}
            snapshotOnly={isImportedSnapshotResult}
          />
          <div style={{ display: "grid", gap: 12 }}>
            {visibleChains.map((chain, index) => (
              <article key={`${chain.compound}-${index}`} style={getSurfaceCardStyle()}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <p style={{ color: "#0d9488", fontWeight: 700, margin: 0, fontSize: 13 }}>
                    {isProviderNetworkResult
                      ? `链 #${index + 1} · 置信度 ${formatScore(chain.score)} · ${getNetworkTargetEvidenceTypeLabel(chain.target_evidence_type)}`
                      : `链 #${index + 1} · 演示链路（mock 占位，非真实置信度）`}
                  </p>
                  <span
                    aria-label={`证据分级 ${getNetworkEvidenceLevelLabel(chain.evidence_level)}`}
                    title="依据网络药理学评价方法指南的可靠性原则给出的确定性证据等级，不表示概率或疗效。"
                    style={{
                      border: "1px solid var(--qiyan-line)",
                      borderRadius: 999,
                      background: "var(--qiyan-surface-3)",
                      color: "var(--qiyan-muted)",
                      fontSize: 12,
                      fontWeight: 700,
                      padding: "2px 10px",
                    }}
                  >
                    证据分级 · {getNetworkEvidenceLevelLabel(chain.evidence_level)}
                  </span>
                </div>
                <p style={{ color: "var(--qiyan-ink)", fontSize: 18, margin: "8px 0 0", lineHeight: 1.6 }}>
                  {chain.herb} → {chain.compound} → {chain.target} → {chain.pathway} → {chain.disease}
                </p>
                <div style={{ display: "grid", gap: 6, marginTop: 12 }}>
                  <p style={{ color: "var(--qiyan-muted)", fontSize: 13, fontWeight: 700, margin: 0 }}>
                    相关实体
                  </p>
                  <EntityChips ids={chain.related_entity_ids} emptyHint="当前 mock 链未返回可跳转实体。" />
                </div>
                {isProviderNetworkResult && chain.evidence_refs && chain.evidence_refs.length > 0 ? (
                  <p style={{ color: "var(--qiyan-muted-2)", fontSize: 13, margin: "10px 0 0" }}>
                    Evidence refs：{chain.evidence_refs.join(", ")}
                  </p>
                ) : null}
                <div
                  aria-label="链路跳转"
                  style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 14 }}
                >
                  <a
                    href={`/literature?q=${encodeURIComponent(chain.target)}`}
                    style={{ color: "#0f766e", fontSize: 14, fontWeight: 700 }}
                  >
                    查相关文献
                  </a>
                  <a
                    href={`/rag?question=${encodeURIComponent(`请基于证据解释 ${chain.target} 与特应性皮炎的关系`)}`}
                    style={{ color: "#0f766e", fontSize: 14, fontWeight: 700 }}
                  >
                    去 RAG 提问
                  </a>
                  {chain.related_entity_ids.length > 0 ? (
                    <a
                      href={buildNetworkFocusHref(chain.related_entity_ids[0])}
                      style={{ color: "#0f766e", fontSize: 14, fontWeight: 700 }}
                    >
                      聚焦首个实体
                    </a>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
          {isProviderNetworkResult && result.data_sources && result.data_sources.length > 0 ? (
            <div style={{ marginTop: 28 }}>
              <h3 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: "0 0 8px" }}>数据来源与缓存</h3>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14, textAlign: "left" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid var(--qiyan-line)" }}>
                      <th style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>Source</th>
                      <th style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>Record ID</th>
                      <th style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>缓存/实时</th>
                      <th style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>Retrieved at</th>
                      <th style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>Usage note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.data_sources.map((source, idx) => (
                      <tr
                        key={`${source.name}-${source.cache_key ?? idx}`}
                        style={{
                          borderBottom: "1px solid var(--qiyan-line)",
                          background: idx % 2 === 0 ? "var(--qiyan-surface)" : "var(--qiyan-surface-3)",
                        }}
                      >
                        <td style={{ padding: "10px 8px", color: "var(--qiyan-ink)", fontWeight: 700 }}>
                          {source.name}
                        </td>
                        <td style={{ padding: "10px 8px", color: "var(--qiyan-muted-2)", fontFamily: "monospace" }}>
                          {source.source_record_id ?? "无"}
                        </td>
                        <td style={{ padding: "10px 8px", color: "#0f766e", fontWeight: 700 }}>
                          {source.from_cache ? "缓存" : "实时"}
                        </td>
                        <td style={{ padding: "10px 8px", color: "var(--qiyan-muted-2)" }}>
                          {source.retrieved_at ?? "无"}
                        </td>
                        <td style={{ padding: "10px 8px", color: "var(--qiyan-muted)", fontSize: 13 }}>
                          {source.license_note ?? "无"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
          {isProviderNetworkResult && result.pipeline_steps && result.pipeline_steps.length > 0 ? (
            <div style={{ marginTop: 28 }}>
              <h3 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: "0 0 8px" }}>运行步骤</h3>
              <div style={{ display: "grid", gap: 8 }}>
                {result.pipeline_steps.map((step) => (
                  <div
                    key={step.name}
                    style={{
                      border: "1px solid var(--qiyan-line)",
                      borderRadius: 8,
                      padding: "10px 12px",
                      background: "var(--qiyan-surface)",
                      color: "var(--qiyan-muted-2)",
                    }}
                  >
                    <strong style={{ color: "var(--qiyan-ink)" }}>{step.name}</strong>
                    <span> · {step.status}</span>
                    <span> · cache hits {step.cache_hit_count}</span>
                    {step.warning ? <span> · {step.warning}</span> : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {result.warnings && result.warnings.length > 0 ? (
            <div
              role="note"
              aria-label="运行警告"
              style={{
                marginTop: 28,
                border: "1px solid rgba(180, 83, 9, 0.28)",
                borderRadius: 8,
                background: "rgba(255, 251, 235, 0.78)",
                padding: "12px 14px",
              }}
            >
              <h3 style={{ color: "var(--qiyan-ink)", fontSize: 18, margin: "0 0 8px" }}>运行警告</h3>
              <ul style={{ margin: 0, paddingLeft: 18, color: "var(--qiyan-muted-2)", lineHeight: 1.65 }}>
                {result.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {!isImportedSnapshotResult && result.enrichment && result.enrichment.terms.length > 0 ? (
            <div style={{ marginTop: 32 }}>
              <h3 style={{ color: "var(--qiyan-ink)", fontSize: 20, margin: "0 0 8px" }}>富集分析结果</h3>
              <p style={{ color: "var(--qiyan-muted-2)", marginBottom: 16, lineHeight: 1.6 }}>
                输入基因数：{result.enrichment.input_gene_count} | 背景基因数：{result.enrichment.background_gene_count}
              </p>
              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: 14,
                    textAlign: "left",
                  }}
                >
                  <thead>
                    <tr style={{ borderBottom: "2px solid var(--qiyan-line)" }}>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>Term ID</th>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>通路/功能</th>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>类别</th>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>重叠基因</th>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>P-value</th>
                      <th style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontWeight: 700 }}>基因列表</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.enrichment.terms.slice(0, 10).map((term, idx) => (
                      <tr
                        key={term.term_id}
                        style={{
                          borderBottom: "1px solid var(--qiyan-line)",
                          background: idx % 2 === 0 ? "var(--qiyan-surface)" : "var(--qiyan-surface-3)",
                        }}
                      >
                        <td style={{ padding: "12px 8px", color: "var(--qiyan-muted-2)", fontFamily: "monospace" }}>
                          {term.term_id}
                        </td>
                        <td style={{ padding: "12px 8px", color: "var(--qiyan-ink)" }}>
                          {term.term_name_zh || term.term_name}
                        </td>
                        <td style={{ padding: "12px 8px", color: "var(--qiyan-muted-2)" }}>{term.category}</td>
                        <td style={{ padding: "12px 8px", color: "#0d9488", fontWeight: 700 }}>
                          {term.overlap_count}/{term.gene_count}
                        </td>
                        <td style={{ padding: "12px 8px", color: "var(--qiyan-muted-2)", fontFamily: "monospace" }}>
                          {term.p_value.toExponential(2)}
                        </td>
                        <td style={{ padding: "12px 8px", color: "var(--qiyan-muted)", fontSize: 13 }}>
                          {term.genes.join(", ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.enrichment.terms.length > 10 ? (
                <p style={{ color: "var(--qiyan-muted-2)", marginTop: 12, fontSize: 13 }}>
                  显示前 10 条结果，共 {result.enrichment.terms.length} 条富集通路/功能。
                </p>
              ) : null}
            </div>
          ) : null}
          <p style={{ color: "var(--qiyan-muted-2)", marginTop: 16, marginBottom: 0, lineHeight: 1.6 }}>
            {result.disclaimer}
          </p>
          <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--qiyan-line)" }}>
            <h3 style={{ color: "var(--qiyan-ink)", fontSize: 18, margin: "0 0 8px" }}>组学验证（omics DEG 投影）</h3>
            <p style={{ color: "var(--qiyan-muted-2)", margin: "0 0 12px", lineHeight: 1.6 }}>
              对已冻结的组学快照按 GSE 登录号做确定性 DEG 投影：只输出谱系匹配的候选基因
              （待人工确认），不改就绪状态、不写谱系。快照需先经组学导入核验冻结；
              无对应快照或未通过核验时，后端会如实拒绝本次请求。
            </p>
            <form
              onSubmit={runOmicsVerification}
              style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}
            >
              <input
                value={omicsAccession}
                onChange={(event) => setOmicsAccession(event.target.value)}
                placeholder="GSE 登录号，如 GSE16161"
                aria-label="组学快照 GSE 登录号"
              />
              <button
                type="submit"
                disabled={omicsBusy || !omicsAccession.trim()}
                style={{
                  border: 0,
                  borderRadius: 8,
                  background: omicsBusy ? "#94a3b8" : "#0d9488",
                  color: "white",
                  fontSize: 14,
                  fontWeight: 700,
                  padding: "10px 16px",
                  minHeight: 44,
                }}
              >
                {omicsBusy ? "投影计算中..." : "核验并投影"}
              </button>
            </form>
            {omicsSummary ? (
              <p style={{ color: "var(--qiyan-ink)", marginTop: 12, marginBottom: 0 }}>
                {omicsSummary}
              </p>
            ) : null}
            {omicsMessage ? (
              <p style={{ color: "var(--qiyan-muted-2)", marginTop: 12, marginBottom: 0 }}>
                {omicsMessage}
              </p>
            ) : null}
          </div>
        </section>
      ) : phase === "idle" ? (
        <StatusPanel message="输入复方或单味中药名称开始分析，系统会返回「成分-靶点-通路-疾病」机制线索链（当前为演示数据，非正式网络药理学结论）。例如：消风散、黄芪。" />
      ) : isBusy ? (
        <StatusPanel message={`分析任务运行中... 当前进度 ${progress}%。`} />
      ) : null}
    </div>
  );
}
