"""Unit tests for build_network_report_markdown service function."""

import pytest

from app.schemas.network import (
    EnrichmentResult,
    EnrichmentTerm,
    NetworkAnalysisResult,
    NetworkChain,
    NetworkCompoundTargetVerifiedSnapshot,
    NetworkDataSource,
    NetworkDiseaseTargetImportSnapshot,
    NetworkDiseaseTargetVerifiedSnapshot,
    NetworkPipelineStep,
    NetworkResearchProtocol,
)
from app.services.network_lineage import build_network_report_markdown, build_target_lineage

DISCLAIMER = "非诊断结论、需结合临床。"

_SAMPLE_CHAIN = NetworkChain(
    herb="黄芩",
    compound="baicalin",
    target="IL6",
    pathway="inflammatory response",
    disease="AD",
    score=0.85,
    related_entity_ids=["herb-001", "compound-001"],
)

_SAMPLE_RESULT = NetworkAnalysisResult(
    task_id="test-task",
    query="黄芩",
    analysis_type="herb",
    chains=[_SAMPLE_CHAIN],
    disclaimer=DISCLAIMER,
)


def _make_result(**overrides: object) -> NetworkAnalysisResult:
    """Create a NetworkAnalysisResult with sensible defaults, allowing overrides."""
    defaults = {
        "task_id": "test-task",
        "query": "黄芩",
        "analysis_type": "herb",
        "chains": [_SAMPLE_CHAIN],
        "disclaimer": DISCLAIMER,
    }
    defaults.update(overrides)
    return NetworkAnalysisResult(**defaults)  # type: ignore[arg-type]


def test_build_report_includes_disclaimer():
    md = build_network_report_markdown(_SAMPLE_RESULT)
    assert DISCLAIMER in md


def test_build_report_exposes_research_protocol_and_readiness_blockers():
    result = _make_result(
        research_protocol={
            "disease": "atopic_dermatitis",
            "phenotype": "特应性皮炎伴 2 型炎症与皮肤屏障异常",
            "species": "Homo sapiens",
            "evidence_policy": "direct_human_first",
            "query_date": "2026-07-11",
        },
        readiness={
            "protocol_complete": True,
            "formal_network_ready": False,
            "blocking_reasons": ["当前任务使用 mock 数据，不能进入正式网络药理学研究。"],
        },
    )

    md = build_network_report_markdown(result)

    assert "## 研究协议与科研门禁" in md
    assert "特应性皮炎伴 2 型炎症与皮肤屏障异常" in md
    assert "Homo sapiens" in md
    assert "direct_human_first" in md
    assert "2026-07-11" in md
    assert "formal_network_ready：否" in md
    assert "当前任务使用 mock 数据" in md


def test_build_report_keeps_target_sets_separate_and_exports_row_lineage():
    result = _make_result(
        target_lineage={
            "observation_unit": "target_record",
            "disease_targets": [],
            "compound_targets": [
                {
                    "raw_identifier": "IL6",
                    "canonical_symbol": "IL6",
                    "source_database": "qiyan_sample_network",
                    "database_version": None,
                    "query_date": "2026-07-11",
                    "species": "Homo sapiens",
                    "source_score": 0.85,
                    "applied_threshold": None,
                    "identifier_mapping": "identity_symbol",
                    "evidence_origin": "mock",
                    "source_record_ids": ["target-il6"],
                    "automatic_status": "extracted",
                    "adjudication_status": "pending",
                    "decision": "unreviewed",
                }
            ],
            "intersection_targets": [],
            "disease_target_count": 0,
            "compound_target_count": 1,
            "intersection_target_count": 0,
            "warnings": ["当前 pipeline 未采集独立疾病靶点集合。"],
        }
    )

    md = build_network_report_markdown(result)

    assert "## 靶点集合与逐行 Lineage" in md
    assert "- 疾病靶点：0" in md
    assert "- 成分靶点：1" in md
    assert "- 派生候选交集：0" in md
    assert "独立疾病靶点集合" in md
    assert "| Lineage row ID | Raw ID | Canonical | Source | Version |" in md
    assert "IL6" in md
    assert "qiyan_sample_network" in md
    assert "pending" in md
    assert "unreviewed" in md
    assert "核心靶点" not in md


def test_build_report_exports_disease_import_provenance_and_bilateral_intersection_refs():
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    imported = NetworkDiseaseTargetImportSnapshot(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype=protocol.phenotype,
        species=protocol.species,
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatypes": ["genetic_association"]},
        query_date=protocol.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        records=[
            {
                "raw_identifier": "ENSG00000136244",
                "canonical_symbol": "IL6",
                "source_record_id": "EFO_0000274:ENSG00000136244",
                "source_score": 0.91,
            }
        ],
        provenance_verification_status="unverified_client_import",
        import_payload_sha256="a" * 64,
    )
    lineage = build_target_lineage([_SAMPLE_CHAIN], protocol, "mock", imported)
    result = _make_result(research_protocol=protocol, target_lineage=lineage)

    md = build_network_report_markdown(result)

    assert "### 疾病导入来源" in md
    assert "open_targets_association_v1" in md
    assert "Open Targets Platform" in md
    assert "25.06" in md
    assert "EFO_0000274" in md
    assert "unverified_client_import" in md
    assert "a" * 64 in md
    assert "| Lineage row ID | Raw ID | Canonical | Source |" in md
    assert "ENSG00000136244" in md
    assert "association_score" in md
    assert "### 派生候选交集" in md
    assert "canonical_symbol_exact_match_v1" in md
    assert lineage.disease_targets[0].lineage_row_id in md
    assert lineage.compound_targets[0].lineage_row_id in md
    assert "payload 哈希只证明导入内容完整性" in md


def test_build_report_exports_verified_raw_artifact_provenance_boundary() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    imported = NetworkDiseaseTargetVerifiedSnapshot(
        source_profile="open_targets_association_v1",
        disease="atopic_dermatitis",
        phenotype=protocol.phenotype,
        species=protocol.species,
        source_database="Open Targets Platform",
        database_version="25.06",
        source_query_id="EFO_0000274",
        source_query_label="atopic eczema",
        source_query_parameters={"datatype": "overall"},
        query_date=protocol.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="association_score",
        applied_threshold=0.6,
        threshold_operator="gte",
        identifier_mapping="Ensembl target approvedSymbol",
        identifier_mapping_version="25.06",
        records=[],
        provenance_verification_status="server_verified_raw_artifact",
        import_payload_sha256="a" * 64,
        source_artifact_sha256="b" * 64,
        source_artifact_filename="open-targets.jsonl",
        source_artifact_media_type="application/x-ndjson",
        usage_license_note="Open Targets Platform data; see platform terms.",
    )
    lineage = build_target_lineage([], protocol, "live", imported)

    md = build_network_report_markdown(
        _make_result(
            research_protocol=protocol,
            target_lineage=lineage,
            data_mode="live",
            chains=[],
        )
    )

    assert "server_verified_raw_artifact" in md
    assert "b" * 64 in md
    assert "open-targets.jsonl" in md
    assert "application/x-ndjson" in md
    assert "Open Targets Platform data; see platform terms." in md
    assert "不证明 release 选择正确" in md
    assert "不证明靶点有生物学意义" in md
    assert "客户端导入声明零命中" not in md


def test_build_report_exports_verified_compound_raw_artifact_provenance_boundary() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    imported = NetworkCompoundTargetVerifiedSnapshot(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={"assay_organism": "Homo sapiens", "pchembl_value_min": 6.0},
        query_date=protocol.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34",
        usage_license_note="ChEMBL data; see database terms.",
        records=[
            {
                "raw_identifier": "CHEMBL1792",
                "canonical_symbol": "IL6",
                "source_record_id": "CHEMBL_ACTIVITY_1001",
                "source_score": 6.4,
            }
        ],
        provenance_verification_status="server_verified_raw_artifact",
        import_payload_sha256="c" * 64,
        source_artifact_sha256="d" * 64,
        source_artifact_filename="chembl-known-activities.json",
        source_artifact_media_type="application/json",
    )
    lineage = build_target_lineage(
        [],
        protocol,
        "live",
        compound_target_import=imported,
    )

    md = build_network_report_markdown(
        _make_result(
            research_protocol=protocol,
            target_lineage=lineage,
            source_task_id="network-" + "a" * 32,
            data_mode="live",
            chains=[],
        )
    )

    assert "### 成分导入来源" in md
    assert "chembl_known_activity_v1" in md
    assert "CHEMBL1201587" in md
    assert "Quercetin" in md
    assert "pchembl_value gte 6.0" in md
    assert "server_verified_raw_artifact" in md
    assert "c" * 64 in md
    assert "d" * 64 in md
    assert "chembl-known-activities.json" in md
    assert "ChEMBL data; see database terms." in md
    assert "Submitted artifact filename (untrusted label)" in md
    assert "Submitted artifact media type (untrusted label)" in md
    assert "不证明 compound-target 边具有生物学意义" in md
    assert "来源疾病任务：network-" + "a" * 32 in md
    assert "尚未生成可复算网络或通路结果" in md
    assert "显式 opt-in 真实数据链路" not in md

    with pytest.raises(ValueError, match="snapshot-only"):
        build_network_report_markdown(
            _make_result(
                research_protocol=protocol,
                target_lineage=lineage,
                source_task_id="network-" + "a" * 32,
                data_mode="live",
                chains=[_SAMPLE_CHAIN],
            )
        )


def test_build_report_escapes_compound_artifact_markdown_injection() -> None:
    protocol = NetworkResearchProtocol(
        phenotype="特应性皮炎伴 2 型炎症",
        evidence_policy="direct_human_first",
        query_date="2026-07-11",
    )
    imported = NetworkCompoundTargetVerifiedSnapshot(
        source_profile="chembl_known_activity_v1",
        compound_id="CHEMBL1201587",
        compound_label="Quercetin",
        species="Homo sapiens",
        source_database="ChEMBL",
        database_version="34",
        source_query_id="CHEMBL1201587",
        source_query_label="Quercetin",
        source_query_parameters={"assay_organism": "Homo sapiens", "pchembl_value_min": 6.0},
        query_date=protocol.query_date,
        retrieved_at="2026-07-11T08:30:00Z",
        score_name="pchembl_value",
        applied_threshold=6.0,
        threshold_operator="gte",
        identifier_mapping="ChEMBL target component gene symbol",
        identifier_mapping_version="34\n# injected heading",
        usage_license_note="ChEMBL data; see database terms.",
        records=[
            {
                "raw_identifier": "CHEMBL1792",
                "canonical_symbol": "IL6",
                "source_record_id": "CHEMBL_ACTIVITY_1001",
                "source_score": 6.4,
            }
        ],
        provenance_verification_status="server_verified_raw_artifact",
        import_payload_sha256="c" * 64,
        source_artifact_sha256="d" * 64,
        source_artifact_filename="[artifact](https://attacker.invalid) <img src=x>",
        source_artifact_media_type="application/json",
    )
    lineage = build_target_lineage([], protocol, "live", compound_target_import=imported)

    md = build_network_report_markdown(
        _make_result(
            research_protocol=protocol,
            target_lineage=lineage,
            source_task_id="network-" + "b" * 32,
            data_mode="live",
            chains=[],
        )
    )

    assert "[artifact](https://attacker.invalid)" not in md
    assert "<img src=x>" not in md
    assert "https://attacker.invalid" not in md
    assert "\n# injected heading" not in md
    assert r"\[artifact\]\(https&#58;//attacker.invalid\)" in md
    assert "&lt;img src=x&gt;" in md


def test_build_report_escapes_query_and_phenotype_markdown_injection() -> None:
    result = _make_result(
        query="消风散\n\n![query](https://attacker.invalid/query) <script>",
        research_protocol=NetworkResearchProtocol(
            phenotype="皮损\n\n[phenotype](https://attacker.invalid/phenotype) <img src=x>",
            evidence_policy="direct_human_first",
            query_date="2026-07-11",
        ),
    )

    md = build_network_report_markdown(result)

    assert "![query](https://attacker.invalid/query)" not in md
    assert "[phenotype](https://attacker.invalid/phenotype)" not in md
    assert "<script>" not in md
    assert "<img src=x>" not in md
    assert r"!\[query\]\(https&#58;//attacker.invalid/query\)" in md
    assert r"\[phenotype\]\(https&#58;//attacker.invalid/phenotype\)" in md
    assert "&lt;script&gt;" in md
    assert "&lt;img src=x&gt;" in md


def test_build_report_leads_with_mock_data_publication_boundary():
    md = build_network_report_markdown(_SAMPLE_RESULT)
    assert (
        "> **数据说明**：本报告基于本地演示数据生成，仅用于功能验证与评审走查；"
        "不可作为科研发表、临床决策或真实数据库分析结果。"
    ) in md
    assert md.index("> **数据说明**") < md.index("## 链路结果")


def test_build_report_chains_table():
    md = build_network_report_markdown(_SAMPLE_RESULT)
    # Header row
    assert (
        "| 序号 | 方剂 | 单味中药 | 成分 | 靶点 | 通路 | 疾病 | Mock 置信度 | 相关实体 ID |" in md
    )
    # Data row: herb=黄芩, compound=baicalin, target=IL6, score=85%
    assert "黄芩" in md
    assert "baicalin" in md
    assert "IL6" in md
    assert "85%" in md
    # formula is None → "无"
    assert "| 无 | 黄芩 |" in md or "无" in md


def test_build_report_empty_chains():
    result = _make_result(chains=[])
    md = build_network_report_markdown(result)
    assert "（当前报告没有可导出的机制链路。）" in md


def test_build_report_with_enrichment():
    enrichment = EnrichmentResult(
        analysis_type="combined",
        input_gene_count=5,
        background_gene_count=20000,
        terms=[
            EnrichmentTerm(
                term_id="GO:0006954",
                term_name="inflammatory response",
                term_name_zh="炎症反应",
                category="GO_BP",
                gene_count=200,
                overlap_count=3,
                p_value=1.23e-4,
                adjusted_p_value=2.46e-3,
                genes=["IL6", "TNF", "IL1B"],
            ),
        ],
        timestamp="2025-01-01T00:00:00+00:00",
    )
    result = _make_result(enrichment=enrichment)
    md = build_network_report_markdown(result)

    assert "## 富集分析结果" in md
    assert "输入基因数：5" in md
    assert "背景基因数：20000" in md
    assert "GO:0006954" in md
    assert "炎症反应" in md
    assert "3/200" in md
    assert "1.23e-04" in md
    assert "2.46e-03" in md
    assert "IL6, TNF, IL1B" in md
    assert "### 参数说明" in md


def test_build_report_without_enrichment():
    result = _make_result(enrichment=None)
    md = build_network_report_markdown(result)
    assert "## 富集分析结果" not in md


def test_build_report_enrichment_with_empty_terms_is_omitted():
    enrichment = EnrichmentResult(
        analysis_type="combined",
        input_gene_count=5,
        background_gene_count=20000,
        terms=[],
        timestamp="2025-01-01T00:00:00+00:00",
    )
    result = _make_result(enrichment=enrichment)
    md = build_network_report_markdown(result)
    assert "## 富集分析结果" not in md


def test_build_report_formula_type_label():
    result = _make_result(analysis_type="formula")
    md = build_network_report_markdown(result)
    assert "分析类型：复方" in md


def test_build_report_herb_type_label():
    result = _make_result(analysis_type="herb")
    md = build_network_report_markdown(result)
    assert "分析类型：单味中药" in md


def test_build_report_boundary_notes():
    md = build_network_report_markdown(_SAMPLE_RESULT)
    assert "## 边界说明" in md
    assert "不是正式网络药理学计算。" in md
    assert "富集分析基于本地 JSON 字典（mock），不代表真实 KEGG REST API 或 STRING 数据库。" in md
    assert "不构成诊断或治疗建议" in md


def test_build_report_network_graph_placeholder():
    md = build_network_report_markdown(_SAMPLE_RESULT)
    assert "## 网络图" in md
    assert "![成分-靶点-通路网络图](placeholder-network-graph.png)" in md
    assert "*注：图片占位符，实际图片生成功能待后续实现*" in md


def test_build_report_custom_exported_at():
    md = build_network_report_markdown(_SAMPLE_RESULT, exported_at="2025-06-01T12:00:00+00:00")
    assert "2025-06-01T12:00:00+00:00" in md


def test_build_report_pipe_escaping():
    chain = NetworkChain(
        herb="黄芩|苦参",
        compound="baicalin",
        target="IL6",
        pathway="inflammatory|response",
        disease="AD",
        score=0.85,
        related_entity_ids=[],
    )
    result = _make_result(chains=[chain])
    md = build_network_report_markdown(result)
    # Pipes inside cells should be escaped
    assert "黄芩\\|苦参" in md
    assert "inflammatory\\|response" in md


def test_build_report_formula_chain_shows_formula():
    chain = NetworkChain(
        herb="黄芩",
        formula="消风散",
        compound="baicalin",
        target="IL6",
        pathway="inflammatory response",
        disease="AD",
        score=0.85,
        related_entity_ids=["herb-001"],
    )
    result = _make_result(chains=[chain])
    md = build_network_report_markdown(result)
    assert "消风散" in md


def test_build_report_includes_live_provenance_sections():
    chain = NetworkChain(
        herb="黄芪",
        compound="Astragaloside IV",
        target="IL6",
        pathway="TNF signaling pathway",
        disease="Atopic dermatitis",
        score=0.8,
        evidence_refs=["CHEMBLASSAY-HQ-1"],
        target_evidence_type="known_activity",
    )
    result = _make_result(
        data_mode="live",
        chains=[chain],
        data_sources=[
            NetworkDataSource(
                name="chembl",
                source_record_id="CHEMBLASSAY-HQ-1",
                url="https://www.ebi.ac.uk/chembl/",
                retrieved_at="2026-06-08T00:00:00+00:00",
                license_note="ChEMBL activity cache/import.",
                cache_key="chembl-v1-abc",
                from_cache=True,
            )
        ],
        pipeline_steps=[
            NetworkPipelineStep(
                name="known-activity-targets",
                status="completed",
                duration_ms=12,
                external_request_count=0,
                cache_hit_count=1,
            )
        ],
        warnings=["Prediction target file is not configured or does not exist."],
    )

    md = build_network_report_markdown(result)

    assert "## 数据来源与参数版本" in md
    assert "数据模式：live" in md
    assert "chembl" in md
    assert "CHEMBLASSAY-HQ-1" in md
    assert "## 运行步骤" in md
    assert "known-activity-targets" in md
    assert "## 运行警告" in md
    assert "Prediction target file is not configured or does not exist." in md
    assert "已知活性证据" in md
