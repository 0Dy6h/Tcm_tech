"""Tests for network chain evidence-level grading (ADR-0015).

The evidence level is a deterministic function of ``data_mode`` +
``target_evidence_type`` + ``evidence_refs``. Mock chains are hard-bounded to
the lowest level so demo output can never masquerade as guideline-grade
reliability.
"""

from app.schemas.network import NetworkChain
from app.services.network_lineage import (
    build_network_report_markdown,
    derive_chain_evidence_level,
    grade_chains_evidence,
)


def _chain(**overrides: object) -> NetworkChain:
    defaults: dict[str, object] = {
        "herb": "黄芩",
        "compound": "baicalin",
        "target": "IL6",
        "pathway": "inflammatory response",
        "disease": "AD",
        "score": 0.8,
    }
    defaults.update(overrides)
    return NetworkChain(**defaults)  # type: ignore[arg-type]


def test_mock_chain_is_always_mock_inferred():
    chain = _chain()
    assert derive_chain_evidence_level(chain, data_mode="mock") == "mock_inferred"


def test_mock_chain_cannot_be_upgraded_by_target_evidence_type():
    # Even if a stray field looks strong, a mock chain stays lowest.
    chain = _chain(target_evidence_type="known_activity", evidence_refs=["X"])
    assert derive_chain_evidence_level(chain, data_mode="mock") == "mock_inferred"


def test_live_known_activity_is_experimental():
    chain = _chain(target_evidence_type="known_activity", evidence_refs=["CHEMBL-1"])
    assert derive_chain_evidence_level(chain, data_mode="live") == "experimental"


def test_live_predicted_is_predicted():
    chain = _chain(target_evidence_type="predicted")
    assert derive_chain_evidence_level(chain, data_mode="live") == "predicted"


def test_live_mixed_is_literature_supported():
    chain = _chain(target_evidence_type="mixed", evidence_refs=["ref-1"])
    assert derive_chain_evidence_level(chain, data_mode="live") == "literature_supported"


def test_live_with_refs_but_mock_type_is_literature_supported():
    chain = _chain(target_evidence_type="mock", evidence_refs=["ref-1"])
    assert derive_chain_evidence_level(chain, data_mode="live") == "literature_supported"


def test_live_without_any_evidence_falls_back_to_predicted():
    chain = _chain(target_evidence_type="mock", evidence_refs=[])
    assert derive_chain_evidence_level(chain, data_mode="live") == "predicted"


def test_grade_chains_sets_evidence_level_on_each_chain():
    chains = [_chain(), _chain(target="TNF")]
    graded = grade_chains_evidence(chains, data_mode="mock")
    assert all(c.evidence_level == "mock_inferred" for c in graded)
    # Original chains are not mutated (immutability).
    assert all(c.evidence_level is None for c in chains)


def test_report_includes_evidence_grading_section_for_mock():
    from app.schemas.network import NetworkAnalysisResult

    result = NetworkAnalysisResult(
        task_id="t",
        query="黄芩",
        analysis_type="herb",
        chains=grade_chains_evidence([_chain()], data_mode="mock"),
        disclaimer="非诊断结论、需结合临床。",
    )
    md = build_network_report_markdown(result)
    assert "## 证据分级" in md
    assert "mock_inferred" in md
    assert "不代表指南意义上的可靠性达标" in md


def test_mock_analysis_flow_grades_all_chains_mock_inferred():
    """End-to-end: the real analyze flow grades chains before returning them."""
    from app.services.network_queries import get_network_analysis_result
    from app.services.network_tasks import create_network_analysis_task

    accepted = create_network_analysis_task("消风散", "formula")
    get_network_analysis_result(accepted.task_id)  # first poll → running
    status, response = get_network_analysis_result(accepted.task_id)  # → completed

    assert status == "ok"
    assert response is not None
    assert response.result is not None
    assert response.result.chains
    assert all(c.evidence_level == "mock_inferred" for c in response.result.chains)
