import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildNetworkAnalyzeUrl,
  buildNetworkCompoundImportVerifyUrl,
  buildNetworkDiseaseImportVerifyUrl,
  buildNetworkReportUrl,
  buildNetworkResultUrl,
  getNetworkDataModeLabel,
  getNetworkAnalysisTypeLabel,
  getNetworkTargetEvidenceTypeLabel,
  type NetworkAnalyzeAccepted,
  type NetworkAnalysisResult,
} from "../lib/api/network";

test("buildNetworkAnalyzeUrl returns the analyze endpoint", () => {
  assert.equal(buildNetworkAnalyzeUrl(), "http://127.0.0.1:8010/api/network/analyze");
});

test("verifyNetworkDiseaseImport posts raw artifact metadata as multipart without overriding content type", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        const accepted: NetworkAnalyzeAccepted = {
          task_id: "network-verified-1",
          status: "queued",
          progress: 0,
          data_mode: "mock",
        };
        return accepted;
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { verifyNetworkDiseaseImport } = await import(`../lib/api/network?ts=${Date.now()}`);
    const file = new File(["raw-open-targets-bytes"], "open-targets-25.06.jsonl", {
      type: "application/x-ndjson",
    });
    const accepted = await verifyNetworkDiseaseImport(
      "  消风散  ",
      "formula",
      "direct_human_first",
      {
        source_profile: "open_targets_association_v1",
        disease: "atopic_dermatitis",
        phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
        species: "Homo sapiens",
        source_database: "Open Targets Platform",
        database_version: "25.06",
        source_query_id: "EFO_0000274",
        source_query_label: "atopic eczema",
        source_query_parameters: { datatypes: ["genetic_association"] },
        query_date: "2026-07-11",
        retrieved_at: "2026-07-11T08:30:00Z",
        score_name: "association_score",
        applied_threshold: 0.6,
        threshold_operator: "gte",
        identifier_mapping: "Ensembl target approvedSymbol",
        identifier_mapping_version: "25.06",
        usage_license_note: "Open Targets Platform data usage terms apply.",
      },
      file,
    );

    assert.equal(buildNetworkDiseaseImportVerifyUrl(), "http://127.0.0.1:8010/api/network/disease-import/verify");
    assert.equal(captured[0].url, buildNetworkDiseaseImportVerifyUrl());
    assert.equal(captured[0].init?.method, "POST");
    assert.deepEqual(captured[0].init?.headers, {});
    const body = captured[0].init?.body;
    assert.ok(body instanceof FormData);
    assert.equal(body.get("query"), "消风散");
    assert.equal(body.get("analysis_type"), "formula");
    assert.equal(body.get("evidence_policy"), "direct_human_first");
    assert.equal(body.get("file"), file);
    assert.deepEqual(JSON.parse(String(body.get("metadata"))), {
      source_profile: "open_targets_association_v1",
      disease: "atopic_dermatitis",
      phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
      species: "Homo sapiens",
      source_database: "Open Targets Platform",
      database_version: "25.06",
      source_query_id: "EFO_0000274",
      source_query_label: "atopic eczema",
      source_query_parameters: { datatypes: ["genetic_association"] },
      query_date: "2026-07-11",
      retrieved_at: "2026-07-11T08:30:00Z",
      score_name: "association_score",
      applied_threshold: 0.6,
      threshold_operator: "gte",
      identifier_mapping: "Ensembl target approvedSymbol",
      identifier_mapping_version: "25.06",
      usage_license_note: "Open Targets Platform data usage terms apply.",
    });
    assert.equal(accepted.task_id, "network-verified-1");
    assert.equal(accepted.data_mode, "mock");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("verifyNetworkCompoundImport posts only source task, metadata, and raw file as multipart", async () => {
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        const accepted: NetworkAnalyzeAccepted = {
          task_id: "network-compound-1",
          status: "queued",
          progress: 0,
          data_mode: "mock",
        };
        return accepted;
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { verifyNetworkCompoundImport } = await import(`../lib/api/network?ts=${Date.now()}`);
    const file = new File(["raw-chembl-bytes"], "chembl-known-activities.json", {
      type: "application/json",
    });
    const accepted = await verifyNetworkCompoundImport(
      "network-source-1",
      {
        source_profile: "chembl_known_activity_v1",
        compound_id: "CHEMBL1201587",
        compound_label: "Quercetin",
        species: "Homo sapiens",
        source_database: "ChEMBL",
        database_version: "34",
        source_query_id: "CHEMBL1201587",
        source_query_label: "Quercetin",
        source_query_parameters: {
          assay_organism: "Homo sapiens",
          standard_type: "IC50",
          pchembl_value_min: 6,
        },
        query_date: "2026-07-11",
        retrieved_at: "2026-07-11T08:30:00Z",
        score_name: "pchembl_value",
        applied_threshold: 6,
        threshold_operator: "gte",
        identifier_mapping: "ChEMBL target component gene symbol",
        identifier_mapping_version: "34",
        usage_license_note: "ChEMBL data; see database terms.",
      },
      file,
    );

    assert.equal(
      buildNetworkCompoundImportVerifyUrl(),
      "http://127.0.0.1:8010/api/network/compound-import/verify",
    );
    assert.equal(captured[0].url, buildNetworkCompoundImportVerifyUrl());
    assert.equal(captured[0].init?.method, "POST");
    assert.deepEqual(captured[0].init?.headers, {});
    const body = captured[0].init?.body;
    assert.ok(body instanceof FormData);
    assert.deepEqual([...body.keys()].sort(), ["file", "metadata", "source_task_id"]);
    assert.equal(body.get("source_task_id"), "network-source-1");
    assert.equal(body.get("file"), file);
    assert.equal(JSON.parse(String(body.get("metadata"))).compound_id, "CHEMBL1201587");
    assert.equal("records" in JSON.parse(String(body.get("metadata"))), false);
    assert.equal(accepted.task_id, "network-compound-1");
    assert.equal(accepted.data_mode, "mock");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("buildNetworkResultUrl encodes task id and points at result endpoint", () => {
  assert.equal(
    buildNetworkResultUrl("network-abc123"),
    "http://127.0.0.1:8010/api/network/result/network-abc123",
  );
});

test("getNetworkAnalysisTypeLabel maps formula and herb to display labels", () => {
  assert.equal(getNetworkAnalysisTypeLabel("formula"), "复方");
  assert.equal(getNetworkAnalysisTypeLabel("herb"), "单味中药");
});

test("network provenance label helpers map live data fields to Chinese labels", () => {
  assert.equal(getNetworkDataModeLabel("mock"), "Mock 演示数据");
  assert.equal(getNetworkDataModeLabel("live"), "真实数据 opt-in");
  assert.equal(getNetworkTargetEvidenceTypeLabel("known_activity"), "已知活性证据");
  assert.equal(getNetworkTargetEvidenceTypeLabel("predicted"), "预测靶点");
  assert.equal(getNetworkTargetEvidenceTypeLabel("mixed"), "已知+预测");
});

test("submitNetworkAnalysis posts trimmed query and analysis_type, returns task id", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async json() {
        const accepted: NetworkAnalyzeAccepted = {
          task_id: "network-abc123",
          status: "queued",
          progress: 0,
          data_mode: "mock",
        };
        return accepted;
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { submitNetworkAnalysis } = await import(`../lib/api/network?ts=${Date.now()}`);
    const accepted = await submitNetworkAnalysis("  消风散  ", "formula", {
      disease: "atopic_dermatitis",
      phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
      species: "Homo sapiens",
      evidence_policy: "direct_human_first",
      query_date: "2026-07-11",
    }, {
      source_profile: "open_targets_association_v1",
      disease: "atopic_dermatitis",
      phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
      species: "Homo sapiens",
      source_database: "Open Targets Platform",
      database_version: "25.06",
      source_query_id: "EFO_0000274",
      source_query_label: "atopic eczema",
      source_query_parameters: { datatypes: ["genetic_association"] },
      query_date: "2026-07-11",
      retrieved_at: "2026-07-11T08:30:00Z",
      score_name: "association_score",
      applied_threshold: 0.6,
      threshold_operator: "gte",
      identifier_mapping: "Ensembl target approvedSymbol",
      identifier_mapping_version: "25.06",
      records: [
        {
          raw_identifier: "ENSG00000136244",
          canonical_symbol: "IL6",
          source_record_id: "EFO_0000274:ENSG00000136244",
          source_score: 0.91,
        },
      ],
    });

    assert.equal(captured.length, 1);
    assert.equal(captured[0].url, "http://127.0.0.1:8010/api/network/analyze");
    assert.equal(captured[0].init?.method, "POST");
    const headers = captured[0].init?.headers as Record<string, string>;
    assert.equal(headers["Content-Type"], "application/json");
    assert.equal("X-Access-Token" in headers, false);
    assert.deepEqual(JSON.parse(String(captured[0].init?.body ?? "{}")), {
      query: "消风散",
      analysis_type: "formula",
      research_protocol: {
        disease: "atopic_dermatitis",
        phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
        species: "Homo sapiens",
        evidence_policy: "direct_human_first",
        query_date: "2026-07-11",
      },
      disease_target_import: {
        source_profile: "open_targets_association_v1",
        disease: "atopic_dermatitis",
        phenotype: "特应性皮炎伴 2 型炎症与皮肤屏障异常",
        species: "Homo sapiens",
        source_database: "Open Targets Platform",
        database_version: "25.06",
        source_query_id: "EFO_0000274",
        source_query_label: "atopic eczema",
        source_query_parameters: { datatypes: ["genetic_association"] },
        query_date: "2026-07-11",
        retrieved_at: "2026-07-11T08:30:00Z",
        score_name: "association_score",
        applied_threshold: 0.6,
        threshold_operator: "gte",
        identifier_mapping: "Ensembl target approvedSymbol",
        identifier_mapping_version: "25.06",
        records: [
          {
            raw_identifier: "ENSG00000136244",
            canonical_symbol: "IL6",
            source_record_id: "EFO_0000274:ENSG00000136244",
            source_score: 0.91,
          },
        ],
      },
    });
    assert.equal(accepted.task_id, "network-abc123");
    assert.equal(accepted.status, "queued");
    assert.equal(accepted.data_mode, "mock");
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
  }
});

test("fetchNetworkResult returns the polled response shape", async () => {
  const originalFetch = globalThis.fetch;
  const compoundChildParentLink: Pick<NetworkAnalysisResult, "source_task_id"> = {
    source_task_id: "network-disease-parent-1",
  };
  globalThis.fetch = (async () => {
    return {
      ok: true,
      async json() {
        return {
          task_id: "network-abc123",
          status: "completed",
          progress: 100,
          data_mode: "live",
          error: null,
          warnings: ["Prediction target file is not configured or does not exist."],
          result: {
            task_id: "network-abc123",
            ...compoundChildParentLink,
            query: "消风散",
            analysis_type: "formula",
            data_mode: "live",
            chains: [
              {
                herb: "消风散",
                compound: "槲皮素",
                target: "IL6",
                pathway: "PI3K-Akt signaling pathway",
                disease: "Atopic dermatitis",
                score: 0.87,
                evidence_refs: ["CHEMBLASSAY-1"],
                target_evidence_type: "known_activity",
                related_entity_ids: [
                  "herb-jingjie",
                  "compound-quercetin",
                  "target-il6",
                  "pathway-pi3k-akt",
                ],
              },
            ],
            pipeline_steps: [
              {
                name: "known-activity-targets",
                status: "completed",
                duration_ms: 12,
                external_request_count: 0,
                cache_hit_count: 1,
              },
            ],
            data_sources: [
              {
                name: "chembl",
                source_record_id: "CHEMBLASSAY-1",
                url: "https://www.ebi.ac.uk/chembl/",
                retrieved_at: "2026-06-08T00:00:00Z",
                license_note: "ChEMBL activity cache/import.",
                cache_key: "chembl-v1-abc",
                from_cache: true,
              },
            ],
            warnings: ["Prediction target file is not configured or does not exist."],
            disclaimer: "非诊断结论、需结合临床。",
          },
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkResult } = await import(`../lib/api/network?ts=${Date.now()}`);
    const polled = await fetchNetworkResult("network-abc123");

    assert.equal(polled.status, "completed");
    assert.equal(polled.data_mode, "live");
    assert.equal(polled.warnings[0], "Prediction target file is not configured or does not exist.");
    assert.equal(polled.result?.chains[0].target, "IL6");
    assert.equal(polled.result?.source_task_id, "network-disease-parent-1");
    assert.equal(polled.result?.chains[0].target_evidence_type, "known_activity");
    assert.equal(polled.result?.data_sources[0].name, "chembl");
    assert.equal(polled.result?.pipeline_steps[0].name, "known-activity-targets");
    assert.deepEqual(polled.result?.chains[0].related_entity_ids, [
      "herb-jingjie",
      "compound-quercetin",
      "target-il6",
      "pathway-pi3k-akt",
    ]);
    assert.equal(polled.result?.disclaimer, "非诊断结论、需结合临床。");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("fetchNetworkResult throws when the response is not ok", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    return {
      ok: false,
      async json() {
        return { detail: "Network analysis task not found" };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkResult } = await import(`../lib/api/network?ts=${Date.now()}`);
    await assert.rejects(fetchNetworkResult("network-missing-task"), /Network result request failed/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("buildNetworkReportUrl encodes task id and points at report endpoint", () => {
  assert.equal(
    buildNetworkReportUrl("network-abc123"),
    "http://127.0.0.1:8010/api/network/result/network-abc123/report",
  );
});

test("fetchNetworkReportMarkdown returns markdown text on 200", async () => {
  process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN = "dev-token";
  const originalFetch = globalThis.fetch;
  const captured: { url: URL | RequestInfo; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: URL | RequestInfo, init?: RequestInit) => {
    captured.push({ url, init });
    return {
      ok: true,
      async text() {
        return "# Qiyan Nexus 网络药理学报告导出\n\n- task_id：network-abc123\n";
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkReportMarkdown } = await import(`../lib/api/network?ts=${Date.now()}`);
    const markdown = await fetchNetworkReportMarkdown("network-abc123");

    assert.equal(captured.length, 1);
    assert.equal(captured[0].url, "http://127.0.0.1:8010/api/network/result/network-abc123/report");
    const headers = captured[0].init?.headers as Record<string, string>;
    assert.equal("X-Access-Token" in headers, false);
    assert.ok(markdown.startsWith("# Qiyan Nexus"));
  } finally {
    globalThis.fetch = originalFetch;
    delete process.env.NEXT_PUBLIC_QIYAN_ACCESS_TOKEN;
  }
});

test("fetchNetworkReportMarkdown throws when the response is not ok", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    return {
      ok: false,
      async json() {
        return { detail: "Network analysis task not found" };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkReportMarkdown } = await import(`../lib/api/network?ts=${Date.now()}`);
    await assert.rejects(
      fetchNetworkReportMarkdown("network-missing-task"),
      /Network report request failed/,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("buildNetworkResultUrl appends omics verification params when requested", () => {
  const url = new URL(
    buildNetworkResultUrl("network-abc123", { omicsVerification: true, omicsAccession: "GSE16161" }),
  );
  assert.equal(url.pathname, "/api/network/result/network-abc123");
  assert.equal(url.searchParams.get("omics_verification"), "true");
  assert.equal(url.searchParams.get("omics_accession"), "GSE16161");
  // 不带选项时保持默认路径（既有契约）
  assert.equal(
    buildNetworkResultUrl("network-abc123"),
    "http://127.0.0.1:8010/api/network/result/network-abc123",
  );
});

test("getNetworkOmicsVerificationSummary formats candidate count and top symbols", async () => {
  const { getNetworkOmicsVerificationSummary } = await import("../lib/api/network");
  const projection = {
    policy_id: "omics_transcriptomics_deg_v1",
    snapshot_id: "omics-snapshot-abc",
    accession: "GSE16161",
    comparison: "AD vs control",
    case_group: "case",
    control_group: "control",
    significance_threshold: 0.05,
    log2fc_abs_threshold: 1,
    analyzed_probe_count: 10,
    analyzed_gene_count: 8,
    passing_gene_count: 2,
    sample_groups_used: { case: 3, control: 3 },
    symbol_mapping_rule: "ortho",
    candidates: [
      {
        canonical_symbol: "FLG",
        lineage_row_ids: ["r1"],
        mean_case: 2,
        mean_control: 1,
        log2fc: 1,
        p_value: 0.01,
        adj_p_value: 0.03,
        status: "pending_human_confirmation" as const,
      },
      {
        canonical_symbol: "IVL",
        lineage_row_ids: ["r2"],
        mean_case: 1.5,
        mean_control: 1,
        log2fc: 0.6,
        p_value: 0.02,
        adj_p_value: 0.04,
        status: "pending_human_confirmation" as const,
      },
    ],
    formal_network_ready: false as const,
  };
  assert.equal(
    getNetworkOmicsVerificationSummary(projection),
    "候选基因 2 个：FLG、IVL",
  );
});

test("fetchNetworkResult surfaces the latest plan consumption projection", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    return {
      ok: true,
      async json() {
        return {
          task_id: "network-abc123",
          status: "completed",
          progress: 100,
          data_mode: "mock",
          error: null,
          warnings: [],
          assembly_gate: {
            policy_id: "source_bound_network_assembly_v1",
            state: "assembly_input_ready",
            blockers: [],
            latest_plan: {
              plan_id: "assembly-plan-" + "c".repeat(64),
              policy_id: "source_bound_network_assembly_v1",
              canonical_plan_input_sha256: "c".repeat(64),
              selected_intersection_count: 1,
              created_at: "2026-09-06T10:00:00+00:00",
              assembly_input_ready: true,
              formal_network_ready: false,
              is_consumed: true,
            },
          },
          result: null,
        };
      },
    } as Response;
  }) as typeof globalThis.fetch;

  try {
    const { fetchNetworkResult } = await import(`../lib/api/network?ts=${Date.now()}`);
    const polled = await fetchNetworkResult("network-abc123");

    const latestPlan = polled.assembly_gate?.latest_plan;
    assert.ok(latestPlan);
    assert.equal(latestPlan.is_consumed, true);
    assert.equal(latestPlan.formal_network_ready, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
