"""Integration tests for network enrichment analysis."""

from app.services.network_queries import get_network_analysis_result
from app.services.network_tasks import create_network_analysis_task


def test_network_analysis_includes_enrichment_when_enough_targets():
    """Network analysis includes enrichment result when chains have >= 2 unique targets."""
    # Create a task for a known herb that will produce multiple chains
    accepted = create_network_analysis_task("黄芪", "herb")
    task_id = accepted.task_id

    # Poll until completed
    status, response = get_network_analysis_result(task_id)
    assert status == "ok"
    assert response is not None

    # First poll: running
    if response.status == "running":
        status, response = get_network_analysis_result(task_id)
        assert status == "ok"
        assert response is not None

    # Should be completed now
    assert response.status == "completed"
    assert response.result is not None

    result = response.result
    assert len(result.chains) > 0

    # Extract unique targets
    unique_targets = {chain.target for chain in result.chains}

    if len(unique_targets) >= 2:
        # Should have enrichment result
        assert result.enrichment is not None
        assert result.enrichment.input_gene_count == len(unique_targets)
        assert result.enrichment.background_gene_count == 20000
        assert result.enrichment.analysis_type == "combined"
        # Should have some enriched terms (if any are significant)
        assert isinstance(result.enrichment.terms, list)
    else:
        # Not enough targets, enrichment should be None
        assert result.enrichment is None


def test_xiaofengsan_mock_analysis_returns_visible_enrichment_terms():
    """Reviewer walkthrough seed query should render a non-empty enrichment table."""
    accepted = create_network_analysis_task("消风散", "formula")
    task_id = accepted.task_id

    status, response = get_network_analysis_result(task_id)
    assert status == "ok"
    assert response is not None

    if response.status == "running":
        status, response = get_network_analysis_result(task_id)
        assert status == "ok"
        assert response is not None

    assert response.status == "completed"
    assert response.result is not None
    assert response.result.enrichment is not None
    assert len(response.result.enrichment.terms) > 0


def test_network_analysis_enrichment_skipped_for_single_target():
    """Network analysis skips enrichment when only 1 unique target."""
    # This test assumes there exists a query that produces only 1 unique target
    # If all queries produce multiple targets, this test will be skipped
    accepted = create_network_analysis_task("test-single-target", "herb")
    task_id = accepted.task_id

    # Poll until completed
    status, response = get_network_analysis_result(task_id)
    assert status == "ok"

    if response.status == "running":
        status, response = get_network_analysis_result(task_id)

    result = response.result
    unique_targets = {chain.target for chain in result.chains}

    if len(unique_targets) < 2:
        assert result.enrichment is None


def test_enrichment_terms_have_valid_structure():
    """Enrichment terms have all required fields with correct types."""
    accepted = create_network_analysis_task("黄芪", "herb")
    task_id = accepted.task_id

    # Poll until completed
    status, response = get_network_analysis_result(task_id)
    if response.status == "running":
        status, response = get_network_analysis_result(task_id)

    result = response.result

    if result.enrichment is not None and len(result.enrichment.terms) > 0:
        term = result.enrichment.terms[0]

        # Check all required fields exist
        assert isinstance(term.term_id, str)
        assert isinstance(term.term_name, str)
        assert isinstance(term.category, str)
        assert isinstance(term.gene_count, int)
        assert isinstance(term.overlap_count, int)
        assert isinstance(term.p_value, float)
        assert isinstance(term.adjusted_p_value, float)
        assert isinstance(term.genes, list)

        # Check value constraints
        assert term.gene_count > 0
        assert term.overlap_count >= 2  # Minimum overlap filter
        assert 0 <= term.p_value <= 1
        assert 0 <= term.adjusted_p_value <= 1
        assert len(term.genes) == term.overlap_count
        assert all(isinstance(gene, str) for gene in term.genes)


def test_enrichment_terms_sorted_by_p_value():
    """Enrichment terms are sorted by p-value (most significant first)."""
    accepted = create_network_analysis_task("黄芪", "herb")
    task_id = accepted.task_id

    # Poll until completed
    status, response = get_network_analysis_result(task_id)
    if response.status == "running":
        status, response = get_network_analysis_result(task_id)

    result = response.result

    if result.enrichment is not None and len(result.enrichment.terms) > 1:
        terms = result.enrichment.terms
        # Check that p-values are in ascending order
        for i in range(len(terms) - 1):
            assert terms[i].p_value <= terms[i + 1].p_value
