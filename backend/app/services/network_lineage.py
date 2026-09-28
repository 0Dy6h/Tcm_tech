"""Target lineage construction, readiness gating, evidence grading, report export."""

import json
from datetime import UTC, datetime

from app.schemas.network import (
    AnalysisType,
    DataMode,
    EvidenceLevel,
    NetworkAdjudicationSummary,
    NetworkAnalysisResult,
    NetworkAssemblyGateProjection,
    NetworkChain,
    NetworkCompoundTargetImportProvenance,
    NetworkCompoundTargetSnapshot,
    NetworkDiseaseTargetImportProvenance,
    NetworkDiseaseTargetSnapshot,
    NetworkResearchProtocol,
    NetworkResearchReadiness,
    NetworkTargetIntersectionRow,
    NetworkTargetLineage,
    NetworkTargetLineageRow,
    TargetEvidenceOrigin,
)
from app.services.network_common import (
    _IMPORTED_COMPOUND_SNAPSHOT_BLOCKER,
    _canonical_sha256,
)


def _build_lineage_row_id(set_name: str, row: NetworkTargetLineageRow) -> str:
    identity_payload = {
        "set_kind": set_name,
        "source_database": row.source_database,
        "database_version": row.database_version,
        "source_query": row.source_query,
        "query_date": row.query_date.isoformat(),
        "retrieved_at": row.retrieved_at,
        "species": row.species,
        "source_record_ids": sorted(row.source_record_ids),
        "raw_identifier": row.raw_identifier,
        "canonical_symbol": row.canonical_symbol,
        "source_score": row.source_score,
        "score_name": row.score_name,
        "applied_threshold": row.applied_threshold,
        "threshold_operator": row.threshold_operator,
        "identifier_mapping": row.identifier_mapping,
        "identifier_mapping_version": row.identifier_mapping_version,
    }
    return f"{set_name}-{_canonical_sha256(identity_payload)}"


def _build_intersection_row(
    symbol: str,
    research_protocol: NetworkResearchProtocol,
    disease_targets: list[NetworkTargetLineageRow],
    compound_targets: list[NetworkTargetLineageRow],
) -> NetworkTargetIntersectionRow:
    disease_row_ids = sorted(
        row.lineage_row_id
        for row in disease_targets
        if row.canonical_symbol == symbol and row.lineage_row_id is not None
    )
    compound_row_ids = sorted(
        row.lineage_row_id
        for row in compound_targets
        if row.canonical_symbol == symbol and row.lineage_row_id is not None
    )
    identity_payload = {
        "derivation": "canonical_symbol_exact_match_v1",
        "canonical_symbol": symbol,
        "disease_lineage_row_ids": disease_row_ids,
        "compound_lineage_row_ids": compound_row_ids,
    }
    return NetworkTargetIntersectionRow(
        lineage_row_id=f"intersection-{_canonical_sha256(identity_payload)}",
        canonical_symbol=symbol,
        query_date=research_protocol.query_date,
        species=research_protocol.species,
        disease_lineage_row_ids=disease_row_ids,
        compound_lineage_row_ids=compound_row_ids,
    )


def assess_network_research_readiness(
    research_protocol: NetworkResearchProtocol | None,
    data_mode: DataMode,
    target_lineage: NetworkTargetLineage | None = None,
) -> NetworkResearchReadiness:
    if research_protocol is None:
        return NetworkResearchReadiness()

    blocking_reasons = ["compound-target 边尚未完成人工判定。"]
    if target_lineage is None or target_lineage.compound_import_provenance is None:
        blocking_reasons.insert(0, "compound 来源数据库版本、阈值与标识符映射尚未冻结。")
    if data_mode == "mock":
        blocking_reasons.insert(0, "当前任务使用 mock 数据，不能进入正式网络药理学研究。")
    if target_lineage is not None:
        if target_lineage.compound_import_provenance is not None:
            blocking_reasons.append(_IMPORTED_COMPOUND_SNAPSHOT_BLOCKER)
        if target_lineage.disease_import_provenance is None:
            blocking_reasons.append("缺少独立疾病靶点集合，不能计算派生候选交集。")
        elif (
            target_lineage.disease_import_provenance.provenance_verification_status
            == "unverified_client_import"
        ):
            blocking_reasons.append(
                "疾病靶点来自未验证的客户端导入，尚未通过服务端 connector 或原始快照校验。"
            )
            if not target_lineage.disease_targets:
                blocking_reasons.append(
                    "客户端导入声明疾病靶点查询在当前阈值下零命中，来源与查询执行未验证。"
                )
        elif (
            target_lineage.disease_import_provenance.provenance_verification_status
            == "server_verified_raw_artifact"
        ):
            if target_lineage.compound_import_provenance is None:
                blocking_reasons.append(
                    "疾病来源已服务端核验；compound 来源保真、阈值与人工 adjudication 未完成，不能进入正式研究状态。"
                )
            else:
                blocking_reasons.append(
                    "疾病与 compound 来源已服务端核验；逐边人工 adjudication 未完成，不能进入正式研究状态。"
                )
        if (
            target_lineage.disease_import_provenance is not None
            and not target_lineage.disease_targets
        ):
            blocking_reasons.append("疾病靶点集合为空，无法形成可供人工判定的疾病-成分网络。")
        if (
            target_lineage.disease_import_provenance is not None
            and target_lineage.compound_import_provenance is not None
            and not target_lineage.intersection_targets
        ):
            blocking_reasons.append("疾病与成分靶点的派生交集为空，无法进入正式网络药理学研究。")
        if any(row.database_version is None for row in target_lineage.compound_targets):
            blocking_reasons.append("至少一个成分靶点来源缺少数据库版本。")
        if any(row.adjudication_status == "pending" for row in target_lineage.compound_targets):
            blocking_reasons.append("成分-靶点记录尚未完成人工判定。")
        if any(row.adjudication_status == "pending" for row in target_lineage.disease_targets):
            blocking_reasons.append("疾病靶点记录尚未完成人工判定。")
        if any(row.adjudication_status == "pending" for row in target_lineage.intersection_targets):
            blocking_reasons.append("派生交集记录尚未完成人工判定。")
    return NetworkResearchReadiness(
        protocol_complete=True,
        formal_network_ready=False,
        blocking_reasons=blocking_reasons,
    )


def build_target_lineage(
    chains: list[NetworkChain],
    research_protocol: NetworkResearchProtocol | None,
    data_mode: DataMode,
    disease_target_import: NetworkDiseaseTargetSnapshot | None = None,
    compound_target_import: NetworkCompoundTargetSnapshot | None = None,
) -> NetworkTargetLineage:
    if research_protocol is None:
        return NetworkTargetLineage(warnings=["缺少研究协议，不能建立靶点 lineage。"])

    if compound_target_import is not None:
        compound_targets: list[NetworkTargetLineageRow] = []
        for record in sorted(
            compound_target_import.records,
            key=lambda item: (item.canonical_symbol, item.source_record_id, item.raw_identifier),
        ):
            row = NetworkTargetLineageRow(
                raw_identifier=record.raw_identifier,
                canonical_symbol=record.canonical_symbol,
                source_database=compound_target_import.source_database,
                database_version=compound_target_import.database_version,
                source_query=compound_target_import.source_query_id,
                query_date=compound_target_import.query_date,
                retrieved_at=compound_target_import.retrieved_at.isoformat(),
                species=compound_target_import.species,
                source_score=record.source_score,
                applied_threshold=compound_target_import.applied_threshold,
                threshold_operator=compound_target_import.threshold_operator,
                score_name=compound_target_import.score_name,
                identifier_mapping=compound_target_import.identifier_mapping,
                identifier_mapping_version=compound_target_import.identifier_mapping_version,
                evidence_origin="known_activity",
                source_record_ids=[record.source_record_id],
            )
            compound_targets.append(
                row.model_copy(update={"lineage_row_id": _build_lineage_row_id("compound", row)})
            )
    else:
        rows_by_key: dict[tuple[str, str, str], NetworkTargetLineageRow] = {}
        for chain in chains:
            canonical_symbol = chain.target.strip()
            if not canonical_symbol:
                continue
            source_record_ids = list(chain.evidence_refs)
            if not source_record_ids:
                source_record_ids = [
                    entity_id
                    for entity_id in chain.related_entity_ids
                    if entity_id.startswith("target-")
                ]
            if data_mode == "mock":
                source_database = "qiyan_sample_network"
                evidence_origin: TargetEvidenceOrigin = "mock"
            else:
                source_database = (
                    "ChEMBL"
                    if chain.target_evidence_type == "known_activity"
                    else "network_live_provider"
                )
                evidence_origin = chain.target_evidence_type

            lineage_record_ids = source_record_ids or [""]
            for source_record_id in lineage_record_ids:
                row_key = (canonical_symbol, source_database, source_record_id)
                existing = rows_by_key.get(row_key)
                if existing is not None:
                    rows_by_key[row_key] = existing.model_copy(
                        update={"source_score": max(existing.source_score or 0, chain.score)}
                    )
                    continue
                rows_by_key[row_key] = NetworkTargetLineageRow(
                    raw_identifier=canonical_symbol,
                    canonical_symbol=canonical_symbol,
                    source_database=source_database,
                    database_version=None,
                    query_date=research_protocol.query_date,
                    species=research_protocol.species,
                    source_score=chain.score,
                    applied_threshold=None,
                    identifier_mapping="identity_symbol",
                    evidence_origin=evidence_origin,
                    source_record_ids=[source_record_id] if source_record_id else [],
                )

        compound_targets = [
            row.model_copy(update={"lineage_row_id": _build_lineage_row_id("compound", row)})
            for row in (rows_by_key[key] for key in sorted(rows_by_key))
        ]
    compound_target_symbols = {row.canonical_symbol for row in compound_targets}
    disease_targets: list[NetworkTargetLineageRow] = []
    if disease_target_import is not None:
        disease_targets = [
            NetworkTargetLineageRow(
                raw_identifier=record.raw_identifier,
                canonical_symbol=record.canonical_symbol,
                source_database=disease_target_import.source_database,
                database_version=disease_target_import.database_version,
                source_query=disease_target_import.source_query_id,
                query_date=disease_target_import.query_date,
                retrieved_at=disease_target_import.retrieved_at.isoformat(),
                species=disease_target_import.species,
                source_score=record.source_score,
                applied_threshold=disease_target_import.applied_threshold,
                threshold_operator=disease_target_import.threshold_operator,
                score_name=disease_target_import.score_name,
                identifier_mapping=disease_target_import.identifier_mapping,
                identifier_mapping_version=disease_target_import.identifier_mapping_version,
                evidence_origin="disease_association",
                source_record_ids=[record.source_record_id],
            )
            for record in disease_target_import.records
        ]
        disease_targets = [
            row.model_copy(update={"lineage_row_id": _build_lineage_row_id("disease", row)})
            for row in disease_targets
        ]
    disease_target_symbols = {row.canonical_symbol for row in disease_targets}
    intersection_target_symbols = disease_target_symbols & compound_target_symbols
    intersection_targets = [
        _build_intersection_row(
            symbol,
            research_protocol,
            disease_targets,
            compound_targets,
        )
        for symbol in sorted(intersection_target_symbols)
    ]
    warnings = ["自动提取不等于人工判定；所有靶点记录默认 adjudication_status=pending。"]
    if disease_target_import is None:
        warnings.insert(
            0,
            "当前 pipeline 未采集独立疾病靶点集合；disease_targets 与 intersection_targets 保持空集。",
        )
    else:
        warnings.insert(
            0,
            "intersection_targets 仅由疾病行与成分行的 canonical symbol 服务端复算产生。",
        )
        if disease_target_import.provenance_verification_status == "server_verified_raw_artifact":
            warnings.insert(
                1,
                "疾病靶点由服务端从原始 artifact 解析；字节哈希与解析一致性不证明 release 选择正确或靶点有生物学意义。",
            )
        else:
            warnings.insert(
                1,
                "疾病靶点来源为客户端声明，payload 哈希只证明导入内容完整性，不证明外部来源真实性。",
            )
        if not disease_targets:
            if (
                disease_target_import.provenance_verification_status
                == "server_verified_raw_artifact"
            ):
                warnings.insert(
                    2,
                    "服务端核验的疾病靶点 artifact 在当前阈值下零命中；"
                    "disease_targets 与 intersection_targets 保持空集，且该一致性不证明查询选择科学有效。",
                )
            else:
                warnings.insert(
                    2,
                    "客户端导入声明疾病靶点查询在当前阈值下零命中，来源与查询执行未验证。",
                )
    disease_import_provenance = None
    if disease_target_import is not None:
        disease_import_provenance = NetworkDiseaseTargetImportProvenance(
            **disease_target_import.model_dump(
                exclude={"records"},
            ),
            record_count=len(disease_target_import.records),
        )
    compound_import_provenance = None
    if compound_target_import is not None:
        compound_import_provenance = NetworkCompoundTargetImportProvenance(
            **compound_target_import.model_dump(exclude={"records"}),
            record_count=len(compound_target_import.records),
        )
    return NetworkTargetLineage(
        disease_import_provenance=disease_import_provenance,
        compound_import_provenance=compound_import_provenance,
        disease_targets=disease_targets,
        compound_targets=compound_targets,
        intersection_targets=intersection_targets,
        disease_target_count=len(disease_target_symbols),
        compound_target_count=len(compound_target_symbols),
        intersection_target_count=len(intersection_target_symbols),
        disease_lineage_row_count=len(disease_targets),
        compound_lineage_row_count=len(compound_targets),
        intersection_lineage_row_count=len(intersection_targets),
        warnings=warnings,
    )


def _escape_table_cell(value: str | int | float | None) -> str:
    """Escape a value for use in a Markdown table cell.

    - None / empty string → "无"
    - HTML and Markdown control characters are rendered as literal text
    - Whitespace collapsed to single space
    """
    if value is None or value == "":
        return "无"
    text = str(value)
    text = " ".join(text.split())
    for character in r"\\`*[]()|":
        text = text.replace(character, f"\\{character}")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("://", "&#58;//")
    return text


def _append_target_lineage_table(lines: list[str], rows: list[NetworkTargetLineageRow]) -> None:
    lines.append(
        "| Lineage row ID | Raw ID | Canonical | Source | Version | Source query | Query date | Retrieved at | Species | Score field | Score | Threshold rule | Mapping | Mapping version | Evidence | Auto | Adjudication | Decision | Source record IDs |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---:|---|---|---|---|---|---|---|---|")
    for row in rows:
        threshold_rule = (
            f"{row.threshold_operator} {row.applied_threshold}"
            if row.threshold_operator is not None and row.applied_threshold is not None
            else None
        )
        cells: list[str | int | float | None] = [
            row.lineage_row_id,
            row.raw_identifier,
            row.canonical_symbol,
            row.source_database,
            row.database_version,
            row.source_query,
            row.query_date.isoformat(),
            row.retrieved_at,
            row.species,
            row.score_name,
            row.source_score,
            threshold_rule,
            row.identifier_mapping,
            row.identifier_mapping_version,
            row.evidence_origin,
            row.automatic_status,
            row.adjudication_status,
            row.decision,
            ", ".join(row.source_record_ids),
        ]
        lines.append(f"| {' | '.join(_escape_table_cell(cell) for cell in cells)} |")


def _format_score(score: float) -> str:
    """Format a 0-1 score as a percentage string like '85%'."""
    return f"{int(round(score * 100))}%"


def _format_entity_ids(ids: list[str]) -> str:
    """Format a list of entity IDs as a comma-separated string, or '无' if empty."""
    return ", ".join(ids) if ids else "无"


def _analysis_type_label(analysis_type: AnalysisType) -> str:
    """Return the Chinese display label for an analysis type."""
    return "单味中药" if analysis_type == "herb" else "复方"


def _target_evidence_type_label(value: str) -> str:
    if value == "known_activity":
        return "已知活性证据"
    if value == "predicted":
        return "预测靶点"
    if value == "mixed":
        return "已知+预测"
    return "Mock"


# ── Evidence grading (ADR-0015) ─────────────────────────────
# A mechanism chain's trustworthiness is bounded by its weakest provenance
# link, so mock chains are hard-pinned to the lowest level. Deterministic:
# no randomness, no external calls, no probability/efficacy estimate.
_EVIDENCE_LEVEL_ORDER: list[EvidenceLevel] = [
    "experimental",
    "omics_validated",
    "literature_supported",
    "predicted",
    "mock_inferred",
]
_EVIDENCE_LEVEL_LABELS: dict[EvidenceLevel, str] = {
    "experimental": "实验证据",
    "omics_validated": "组学验证",
    "literature_supported": "文献支撑",
    "predicted": "预测证据",
    "mock_inferred": "演示推断（未验证）",
}


def derive_chain_evidence_level(chain: NetworkChain, *, data_mode: DataMode) -> EvidenceLevel:
    """Deterministically grade one chain's evidence support (ADR-0015)."""
    # Honesty invariant: mock data can never claim real evidence strength.
    if data_mode != "live":
        return "mock_inferred"
    if chain.target_evidence_type == "known_activity":
        return "experimental"
    if chain.target_evidence_type == "mixed" or chain.evidence_refs:
        return "literature_supported"
    # Live but only predicted / unresolved targets: weakest live tier.
    return "predicted"


def grade_chains_evidence(chains: list[NetworkChain], *, data_mode: DataMode) -> list[NetworkChain]:
    """Return new chains with ``evidence_level`` filled (immutable copy)."""
    return [
        chain.model_copy(
            update={"evidence_level": derive_chain_evidence_level(chain, data_mode=data_mode)}
        )
        for chain in chains
    ]


def _evidence_level_label(level: EvidenceLevel | None) -> str:
    return _EVIDENCE_LEVEL_LABELS.get(level or "mock_inferred", "演示推断（未验证）")


def build_network_report_markdown(
    result: NetworkAnalysisResult,
    exported_at: str | None = None,
    adjudication: NetworkAdjudicationSummary | None = None,
    assembly_gate: NetworkAssemblyGateProjection | None = None,
) -> str:
    """Build a Markdown report string equivalent to the frontend
    ``buildNetworkReportMarkdown`` function.

    The output format is strictly aligned with
    ``frontend/lib/network-report-export.ts``.
    """
    adjudication = adjudication or NetworkAdjudicationSummary()
    assembly_gate = assembly_gate or NetworkAssemblyGateProjection()
    has_compound_provenance = result.target_lineage.compound_import_provenance is not None
    if has_compound_provenance and result.source_task_id is None:
        raise ValueError("compound target lineage is missing its immutable source task link")
    if result.source_task_id is not None and not has_compound_provenance:
        raise ValueError("source_task_id is only valid for compound target lineage")
    if has_compound_provenance and (
        result.chains
        or result.enrichment is not None
        or result.ppi_edges
        or result.data_sources
        or result.pipeline_steps
    ):
        raise ValueError("compound target lineage must remain a snapshot-only output")
    timestamp = exported_at or datetime.now(UTC).isoformat()
    lines: list[str] = []
    is_imported_compound_snapshot = result.source_task_id is not None

    # ── Header ──────────────────────────────────────────────
    lines.append("# Qiyan Nexus 网络药理学报告导出")
    lines.append("")
    lines.append(f"- 导出时间（UTC）：{timestamp}")
    lines.append(f"- task_id：{result.task_id}")
    if result.source_task_id is not None:
        lines.append(f"- 来源疾病任务：{_escape_table_cell(result.source_task_id)}")
    lines.append(f"- 分析对象：{_escape_table_cell(result.query)}")
    lines.append(f"- 分析类型：{_analysis_type_label(result.analysis_type)}")
    lines.append(f"- 数据模式：{result.data_mode}")
    lines.append(f"- 链路数量：{len(result.chains)}")
    if is_imported_compound_snapshot:
        lines.append("- 数据来源：服务端核验的疾病/成分靶点快照，尚未生成可复算网络或通路结果")
    elif result.data_mode == "live":
        lines.append("- 数据来源：显式 opt-in 真实数据链路（含缓存/导入来源）")
    else:
        lines.append("- 数据来源：本报告基于本地 mock seed graph 生成")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append(
            "> **数据说明**：当前仅导出不可变靶点 lineage 和服务端派生交集；"
            "未调用 provider 生成机制链、富集、PPI 或通路，不能把快照一致性解释为网络结论。"
        )
    elif result.data_mode == "live":
        lines.append(
            "> **数据说明**：本报告来自显式启用的真实数据链路；仍需核对外部数据库版本、"
            "缓存时间、授权边界与原始记录，不可直接作为临床决策结论。"
        )
    else:
        lines.append(
            "> **数据说明**：本报告基于本地演示数据生成，仅用于功能验证与评审走查；"
            "不可作为科研发表、临床决策或真实数据库分析结果。"
        )
    lines.append("")

    lines.append("## 研究协议与科研门禁")
    lines.append("")
    if result.research_protocol is None:
        lines.append("- 研究协议：缺失（legacy 或不可审计任务）")
    else:
        lines.append(f"- 疾病范围：{result.research_protocol.disease}")
        lines.append(f"- 明确表型：{_escape_table_cell(result.research_protocol.phenotype)}")
        lines.append(f"- 物种：{result.research_protocol.species}")
        lines.append(f"- 证据策略：{result.research_protocol.evidence_policy}")
        lines.append(f"- 查询日期：{result.research_protocol.query_date.isoformat()}")
    lines.append(f"- protocol_complete：{'是' if result.readiness.protocol_complete else '否'}")
    lines.append(
        f"- formal_network_ready：{'是' if result.readiness.formal_network_ready else '否'}"
    )
    if result.readiness.blocking_reasons:
        lines.append("- 阻塞项：")
        for reason in result.readiness.blocking_reasons:
            lines.append(f"  - {_escape_table_cell(reason)}")
    lines.append("")

    lines.append("## 候选装配输入门禁")
    lines.append("")
    lines.append(f"- Policy：{assembly_gate.policy_id}")
    lines.append(f"- 状态：{assembly_gate.state}")
    lines.append("- formal_network_ready：否")
    lines.append(
        "> 候选计划只封存协议、双侧 artifact、冻结 lineage 与判定快照；"
        "不生成网络边，不授权后续 writer，也不表示科研就绪。"
    )
    if assembly_gate.blockers:
        lines.append("- 阻塞项：")
        for blocker in assembly_gate.blockers:
            row_suffix = f"（{len(blocker.row_ids)} 行）" if blocker.row_ids else ""
            lines.append(f"  - {blocker.code}{row_suffix}")
    if assembly_gate.latest_plan is not None:
        lines.append(f"- 最新计划：{assembly_gate.latest_plan.plan_id}")
        lines.append(f"- 纳入交集：{assembly_gate.latest_plan.selected_intersection_count}")
        lines.append(
            f"- Plan input SHA-256：{assembly_gate.latest_plan.canonical_plan_input_sha256}"
        )
        lines.append(
            "- 消费状态：已被 writer 消费（审计记录见消费流）"
            if assembly_gate.latest_plan.is_consumed
            else "- 消费状态：尚未被消费"
        )
    lines.append("")

    lines.append("## 靶点集合与逐行 Lineage")
    lines.append("")
    lines.append(f"- 观察单元汇总：{result.target_lineage.observation_unit}")
    lines.append(
        f"- 疾病/成分观察单元：{result.target_lineage.disease_observation_unit} / "
        f"{result.target_lineage.compound_observation_unit}"
    )
    lines.append(f"- 交集观察单元：{result.target_lineage.intersection_observation_unit}")
    lines.append(
        f"- 疾病靶点：{result.target_lineage.disease_target_count}（lineage rows: {result.target_lineage.disease_lineage_row_count}）"
    )
    lines.append(
        f"- 成分靶点：{result.target_lineage.compound_target_count}（lineage rows: {result.target_lineage.compound_lineage_row_count}）"
    )
    lines.append(
        f"- 派生候选交集：{result.target_lineage.intersection_target_count}（derivation rows: {result.target_lineage.intersection_lineage_row_count}）"
    )
    for warning in result.target_lineage.warnings:
        lines.append(f"- 警告：{_escape_table_cell(warning)}")
    lines.append("")

    lines.append("### 疾病导入来源")
    lines.append("")
    provenance = result.target_lineage.disease_import_provenance
    if provenance is None:
        lines.append("（未提供疾病靶点导入 artifact。）")
    else:
        lines.append(f"- Source profile：{_escape_table_cell(provenance.source_profile)}")
        lines.append(
            f"- Source database/version：{_escape_table_cell(provenance.source_database)} / "
            f"{_escape_table_cell(provenance.database_version)}"
        )
        lines.append(
            f"- Source query：{_escape_table_cell(provenance.source_query_id)} / "
            f"{_escape_table_cell(provenance.source_query_label)}"
        )
        lines.append(
            "- Source query parameters："
            + _escape_table_cell(
                json.dumps(
                    provenance.source_query_parameters,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        )
        lines.append(f"- Retrieved at：{_escape_table_cell(provenance.retrieved_at.isoformat())}")
        lines.append(
            f"- Score/threshold：{provenance.score_name} {provenance.threshold_operator} "
            f"{provenance.applied_threshold}"
        )
        lines.append(
            f"- Identifier mapping/version：{_escape_table_cell(provenance.identifier_mapping)} / "
            f"{_escape_table_cell(provenance.identifier_mapping_version)}"
        )
        lines.append(f"- Imported source records：{provenance.record_count}")
        lines.append(f"- Provenance verification：{provenance.provenance_verification_status}")
        lines.append(f"- Import payload SHA-256：{provenance.import_payload_sha256}")
        if provenance.provenance_verification_status == "server_verified_raw_artifact":
            lines.append(f"- Source artifact SHA-256：{provenance.source_artifact_sha256}")
            lines.append(
                "- Submitted artifact filename (untrusted label)："
                f"{_escape_table_cell(provenance.source_artifact_filename)}"
            )
            lines.append(
                "- Submitted artifact media type (untrusted label)："
                f"{_escape_table_cell(provenance.source_artifact_media_type)}"
            )
            lines.append(
                f"- Usage/license note：{_escape_table_cell(provenance.usage_license_note)}"
            )
            lines.append(
                "> **验证边界**：source artifact 哈希只证明原始文件字节完整性与服务端解析一致性；"
                "filename/media type 是客户端传输标签且不受 manifest 绑定；不证明 release 选择正确，"
                "不证明表型映射正确，也不证明靶点有生物学意义。"
            )
        else:
            lines.append(
                "> **验证边界**：payload 哈希只证明导入内容完整性，不证明外部数据库真实性；"
                "该来源仍需服务端 connector 或原始快照核验。"
            )
    lines.append("")

    lines.append("### 成分导入来源")
    lines.append("")
    compound_provenance = result.target_lineage.compound_import_provenance
    if compound_provenance is None:
        lines.append("（未提供服务端核验的成分靶点原始 artifact。）")
    else:
        lines.append(f"- Source profile：{_escape_table_cell(compound_provenance.source_profile)}")
        lines.append(
            f"- Compound：{_escape_table_cell(compound_provenance.compound_id)} / "
            f"{_escape_table_cell(compound_provenance.compound_label)}"
        )
        lines.append(
            f"- Source database/version：{_escape_table_cell(compound_provenance.source_database)} / "
            f"{_escape_table_cell(compound_provenance.database_version)}"
        )
        lines.append(
            f"- Source query：{_escape_table_cell(compound_provenance.source_query_id)} / "
            f"{_escape_table_cell(compound_provenance.source_query_label)}"
        )
        lines.append(
            "- Source query parameters："
            + _escape_table_cell(
                json.dumps(
                    compound_provenance.source_query_parameters.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        )
        lines.append(
            f"- Retrieved at：{_escape_table_cell(compound_provenance.retrieved_at.isoformat())}"
        )
        lines.append(
            f"- Score/threshold：{compound_provenance.score_name} "
            f"{compound_provenance.threshold_operator} {compound_provenance.applied_threshold}"
        )
        lines.append(
            "- Identifier mapping/version："
            f"{_escape_table_cell(compound_provenance.identifier_mapping)} / "
            f"{_escape_table_cell(compound_provenance.identifier_mapping_version)}"
        )
        lines.append(f"- Imported source records：{compound_provenance.record_count}")
        lines.append(
            f"- Provenance verification：{compound_provenance.provenance_verification_status}"
        )
        lines.append(f"- Import payload SHA-256：{compound_provenance.import_payload_sha256}")
        lines.append(f"- Source artifact SHA-256：{compound_provenance.source_artifact_sha256}")
        lines.append(
            "- Submitted artifact filename (untrusted label)："
            f"{_escape_table_cell(compound_provenance.source_artifact_filename)}"
        )
        lines.append(
            "- Submitted artifact media type (untrusted label)："
            f"{_escape_table_cell(compound_provenance.source_artifact_media_type)}"
        )
        lines.append(
            f"- Usage/license note：{_escape_table_cell(compound_provenance.usage_license_note)}"
        )
        lines.append(
            "> **验证边界**：source artifact 哈希只证明原始文件字节完整性与服务端解析一致性；"
            "filename/media type 是客户端传输标签且不受 manifest 绑定；不证明 release 选择正确，"
            "不证明 target mapping 正确，也不证明 compound-target 边具有生物学意义。"
        )
    lines.append("")

    lines.append("### 疾病靶点集合")
    lines.append("")
    if result.target_lineage.disease_targets:
        _append_target_lineage_table(lines, result.target_lineage.disease_targets)
    elif provenance is not None:
        if provenance.provenance_verification_status == "server_verified_raw_artifact":
            lines.append("（服务端解析的原始 artifact 在声明阈值下零命中。）")
        else:
            lines.append("（客户端导入声明零命中；来源与查询执行尚未由服务端验证。）")
    else:
        lines.append("（未采集独立疾病靶点集合。）")
    lines.append("")

    lines.append("### 成分靶点集合")
    lines.append("")
    if not result.target_lineage.compound_targets:
        lines.append("（未提取成分靶点。）")
    else:
        _append_target_lineage_table(lines, result.target_lineage.compound_targets)
    lines.append("")

    lines.append("### 派生候选交集")
    lines.append("")
    if result.target_lineage.intersection_targets:
        lines.append(
            "| Derivation row ID | Canonical | Derivation | Disease lineage refs | Compound lineage refs | Auto | Adjudication | Decision |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for row in result.target_lineage.intersection_targets:
            cells: list[str | int | float | None] = [
                row.lineage_row_id,
                row.canonical_symbol,
                row.derivation,
                ", ".join(row.disease_lineage_row_ids),
                ", ".join(row.compound_lineage_row_ids),
                row.automatic_status,
                row.adjudication_status,
                row.decision,
            ]
            lines.append(f"| {' | '.join(_escape_table_cell(cell) for cell in cells)} |")
    else:
        lines.append("（没有服务端派生的候选交集；禁止从成分靶点集合自我构造疾病交集。）")
    lines.append("")

    # ── Manual adjudication section (append-only audit data) ──
    lines.append("## 人工判定")
    lines.append("")
    lines.append(
        "> 逐行人工判定是附加审计数据：不改变冻结的靶点 lineage、来源 provenance 或 "
        "formal_network_ready；同一行多次判定时仅展示最新一条。"
    )
    lines.append("")
    lines.append(
        "| Included（纳入） | Excluded（排除） | Needs review（待复核） | Pending（待判定） |"
    )
    lines.append("|---:|---:|---:|---:|")
    lines.append(
        f"| {adjudication.counts.included} | {adjudication.counts.excluded} | "
        f"{adjudication.counts.needs_review} | {adjudication.counts.pending} |"
    )
    lines.append("")
    if not adjudication.current:
        lines.append("（尚无人工判定记录。）")
    else:
        lines.append("| Lineage row ID | 判定 | 理由 | 判定时间（UTC） |")
        lines.append("|---|---|---|---|")
        for entry in adjudication.current:
            adjudication_cells: list[str | int | float | None] = [
                entry.lineage_row_id,
                entry.decision,
                entry.reason,
                entry.decided_at,
            ]
            lines.append(f"| {' | '.join(_escape_table_cell(c) for c in adjudication_cells)} |")
    lines.append("")

    if result.data_mode == "live" and not is_imported_compound_snapshot:
        lines.append("## 数据来源与参数版本")
        lines.append("")
        if result.data_sources:
            lines.append(
                "| Source | Record ID | URL | Retrieved at | Cache | Usage note | Cache key |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for source in result.data_sources:
                cells = [
                    source.name,
                    source.source_record_id,
                    source.url,
                    source.retrieved_at,
                    "cache" if source.from_cache else "live",
                    source.license_note,
                    source.cache_key,
                ]
                escaped = [_escape_table_cell(c) for c in cells]
                lines.append(f"| {' | '.join(escaped)} |")
        else:
            lines.append("（当前结果未返回外部数据来源元数据。）")
        lines.append("")

        lines.append("## 运行步骤")
        lines.append("")
        if result.pipeline_steps:
            lines.append("| Step | Status | Duration ms | Requests | Cache hits | Warning |")
            lines.append("|---|---|---:|---:|---:|---|")
            for step in result.pipeline_steps:
                pipeline_cells: list[str | int | float | None] = [
                    step.name,
                    step.status,
                    step.duration_ms,
                    step.external_request_count,
                    step.cache_hit_count,
                    step.warning,
                ]
                escaped = [_escape_table_cell(c) for c in pipeline_cells]
                lines.append(f"| {' | '.join(escaped)} |")
        else:
            lines.append("（当前结果未返回运行步骤元数据。）")
        lines.append("")

        if result.warnings:
            lines.append("## 运行警告")
            lines.append("")
            for warning in result.warnings:
                lines.append(f"- {_escape_table_cell(warning)}")
            lines.append("")

    # ── Chains table ────────────────────────────────────────
    lines.append("## 链路结果")
    lines.append("")
    if not result.chains:
        lines.append("（当前报告没有可导出的机制链路。）")
    else:
        if result.data_mode == "live":
            lines.append(
                "| 序号 | 方剂 | 单味中药 | 成分 | 靶点 | 靶点证据类型 | 通路 | 疾病 | 置信度 | Evidence refs |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---:|---|")
        else:
            lines.append(
                "| 序号 | 方剂 | 单味中药 | 成分 | 靶点 | 通路 | 疾病 | Mock 置信度 | 相关实体 ID |"
            )
            lines.append("|---|---|---|---|---|---|---|---:|---|")
        for idx, chain in enumerate(result.chains, start=1):
            if result.data_mode == "live":
                cells = [
                    str(idx),
                    chain.formula,
                    chain.herb,
                    chain.compound,
                    chain.target,
                    _target_evidence_type_label(chain.target_evidence_type),
                    chain.pathway,
                    chain.disease,
                    _format_score(chain.score),
                    _format_entity_ids(chain.evidence_refs),
                ]
            else:
                cells = [
                    str(idx),
                    chain.formula,
                    chain.herb,
                    chain.compound,
                    chain.target,
                    chain.pathway,
                    chain.disease,
                    _format_score(chain.score),
                    _format_entity_ids(chain.related_entity_ids),
                ]
            escaped = [_escape_table_cell(c) for c in cells]
            lines.append(f"| {' | '.join(escaped)} |")
    lines.append("")

    # ── Evidence grading section (ADR-0015) ─────────────────
    lines.append("## 证据分级")
    lines.append("")
    lines.append(
        "> 依据《网络药理学评价方法指南》的可靠性/规范性/可解释性原则，对每条机制链按其"
        "最弱一环的来源给出确定性证据等级（不改变链路排序，不表示概率或疗效）。"
    )
    lines.append("")
    grading_counts: dict[EvidenceLevel, int] = {level: 0 for level in _EVIDENCE_LEVEL_ORDER}
    for graded_chain in result.chains:
        grading_counts[graded_chain.evidence_level or "mock_inferred"] += 1
    lines.append("| 证据等级 | Level | 链路数 |")
    lines.append("|---|---|---:|")
    for level in _EVIDENCE_LEVEL_ORDER:
        lines.append(f"| {_evidence_level_label(level)} | `{level}` | {grading_counts[level]} |")
    lines.append("")
    if result.data_mode != "live":
        lines.append(
            "> **边界**：本报告为 mock 演示数据，所有链路证据等级恒为 `mock_inferred`，"
            "不代表指南意义上的可靠性达标，也不可作为真实证据强度。"
        )
        lines.append("")

    # ── Enrichment section ──────────────────────────────────
    if result.enrichment and result.enrichment.terms:
        lines.append("## 富集分析结果")
        lines.append("")
        lines.append(f"- 输入基因数：{result.enrichment.input_gene_count}")
        lines.append(f"- 背景基因数：{result.enrichment.background_gene_count}")
        lines.append(f"- 分析类型：{result.enrichment.analysis_type}")
        lines.append(f"- 富集通路/功能数：{len(result.enrichment.terms)}")
        lines.append("")
        lines.append(
            "| Term ID | 通路/功能 | 类别 | 重叠基因 | P-value | 校正后 P-value | 基因列表 |"
        )
        lines.append("|---|---|---|---:|---:|---:|---|")
        for term in result.enrichment.terms:
            term_name = term.term_name_zh or term.term_name
            overlap = f"{term.overlap_count}/{term.gene_count}"
            p_val = f"{term.p_value:.2e}"
            adj_p_val = f"{term.adjusted_p_value:.2e}"
            genes = ", ".join(term.genes)
            cells = [
                term.term_id,
                term_name,
                term.category,
                overlap,
                p_val,
                adj_p_val,
                genes,
            ]
            escaped = [_escape_table_cell(c) for c in cells]
            lines.append(f"| {' | '.join(escaped)} |")
        lines.append("")
        lines.append("### 参数说明")
        lines.append("")
        lines.append("- **P-value**：超几何分布计算的原始 p 值")
        lines.append("- **校正后 P-value**：Bonferroni 校正后的 p 值")
        lines.append("- **重叠基因**：输入基因与该通路/功能的交集数量")
        lines.append("- **过滤条件**：p < 0.05 且重叠基因数 >= 2")
        lines.append("")

    # ── Network graph placeholder ───────────────────────────
    lines.append("## 网络图")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append("（当前仅有冻结靶点快照，尚未构建可复算的成分-靶点-通路网络图。）")
    else:
        lines.append("![成分-靶点-通路网络图](placeholder-network-graph.png)")
        lines.append("")
        lines.append("*注：图片占位符，实际图片生成功能待后续实现*")
    lines.append("")

    # ── Boundary notes ──────────────────────────────────────
    lines.append("## 边界说明")
    lines.append("")
    if is_imported_compound_snapshot:
        lines.append("- 靶点快照工程一致性不证明来源官方性、release/query 选择或生物学意义。")
        lines.append("- 未完成可复算的成分-靶点-通路网络、富集、PPI 或逐边人工 adjudication。")
    elif result.data_mode == "live":
        lines.append("- 本报告来自显式 opt-in 真实数据链路，仍需人工核对外部来源版本与缓存时间。")
        lines.append("- 预测靶点来自本地导入 artifact，不自动爬取 SwissTargetPrediction。")
        lines.append("- TCMSP 入口仅在 operator 明确允许或已有缓存时使用。")
    else:
        lines.append("- 不是正式网络药理学计算。")
        lines.append(
            "- 富集分析基于本地 JSON 字典（mock），不代表真实 KEGG REST API 或 STRING 数据库。"
        )
    lines.append("- 不构成诊断或治疗建议，实际判断需核对原始文献、参数版本与临床背景。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(result.disclaimer)
    lines.append("")

    return "\n".join(lines)
