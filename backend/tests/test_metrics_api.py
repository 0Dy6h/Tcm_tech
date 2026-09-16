"""Tests for metrics API endpoints."""

from fastapi.testclient import TestClient

from app.core.metrics import record_request_latency, reset_metrics
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_get_performance_metrics_empty():
    reset_metrics()
    response = client.get("/api/metrics/performance")
    assert response.status_code == 200
    assert response.json() == {}


def test_get_performance_metrics_with_data():
    reset_metrics()
    # Simulate some requests
    record_request_latency("/api/rag/answer", 100.0)
    record_request_latency("/api/rag/answer", 200.0)
    record_request_latency("/api/literature", 50.0)

    response = client.get("/api/metrics/performance")
    assert response.status_code == 200

    data = response.json()
    assert "/api/rag/answer" in data
    assert "/api/literature" in data

    rag_stats = data["/api/rag/answer"]
    assert rag_stats["count"] == 2
    assert rag_stats["avg_ms"] == 150.0
    assert rag_stats["min_ms"] == 100.0
    assert rag_stats["max_ms"] == 200.0

    lit_stats = data["/api/literature"]
    assert lit_stats["count"] == 1
    assert lit_stats["avg_ms"] == 50.0


def test_get_endpoint_performance_exists():
    reset_metrics()
    record_request_latency("/api/test/endpoint", 123.45)

    response = client.get("/api/metrics/performance/api/test/endpoint")
    assert response.status_code == 200

    data = response.json()
    assert data["count"] == 1
    assert data["avg_ms"] == 123.45


def test_get_endpoint_performance_with_leading_slash():
    reset_metrics()
    record_request_latency("/api/test", 100.0)

    # Request without leading slash should still work
    response = client.get("/api/metrics/performance/api/test")
    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_get_endpoint_performance_not_found():
    reset_metrics()

    response = client.get("/api/metrics/performance/api/nonexistent")
    assert response.status_code == 200
    assert response.json() is None


def test_metrics_endpoint_records_its_own_performance():
    reset_metrics()

    # Call metrics endpoint multiple times
    client.get("/api/metrics/performance")
    client.get("/api/metrics/performance")

    # Check that the metrics endpoint itself is tracked
    response = client.get("/api/metrics/performance")
    data = response.json()

    # The /api/metrics/performance endpoint should have at least 2 calls
    # Note: The 3rd call's metrics are recorded but returned in the response
    # before being fully processed, so we check for >= 2
    assert "/api/metrics/performance" in data
    assert data["/api/metrics/performance"]["count"] >= 2
