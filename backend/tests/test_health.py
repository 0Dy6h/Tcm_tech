from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_service_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    # Hub fingerprint keys must stay exactly as-is.
    assert body["status"] == "ok"
    assert body["service"] == "qiyan-nexus-api"
    # Default config (hashing embedding, NLI off): warm-up is a no-op.
    assert body["embedding_ready"] is None
    assert body["nli_ready"] is None



def test_model_warmup_is_noop_by_default(monkeypatch):
    from app.core import model_warmup

    monkeypatch.delenv("QIYAN_EMBEDDING_BACKEND", raising=False)
    monkeypatch.delenv("QIYAN_NLI_BACKEND", raising=False)
    assert model_warmup.start_model_warmup("") is None


def test_model_warmup_preloads_enabled_embedding(monkeypatch):
    from app.core import model_warmup

    calls = []

    class FakeModel:
        def encode(self, texts, **_kwargs):
            import numpy as np

            calls.append(texts)
            return np.zeros((len(texts), 512), dtype="float32")

    monkeypatch.setenv("QIYAN_EMBEDDING_BACKEND", "bge")
    monkeypatch.setattr(
        "app.services.retrieval.embedding._load_sentence_transformer", lambda _name: FakeModel()
    )
    monkeypatch.setattr(model_warmup, "_state", {"embedding_ready": None, "nli_ready": None})
    thread = model_warmup.start_model_warmup("")
    assert thread is not None
    thread.join(timeout=5)
    assert calls == [["warmup"]]
    assert model_warmup.warmup_status() == {"embedding_ready": True, "nli_ready": None}
