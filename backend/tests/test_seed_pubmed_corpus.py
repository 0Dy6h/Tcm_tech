import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.seed_pubmed_corpus import main, prepare_isolated_runtime, validate_real_only_corpus


def test_prepare_isolated_runtime_creates_empty_json_state(tmp_path: Path):
    literature_path, chunk_path = prepare_isolated_runtime(tmp_path / "validation")

    assert literature_path.read_text(encoding="utf-8") == "[]\n"
    assert chunk_path.read_text(encoding="utf-8") == "[]\n"


def test_prepare_isolated_runtime_refuses_to_reuse_without_resume(tmp_path: Path):
    runtime_root = tmp_path / "validation"
    prepare_isolated_runtime(runtime_root)

    with pytest.raises(ValueError, match="already exists"):
        prepare_isolated_runtime(runtime_root)


def test_validate_real_only_corpus_rejects_seed_and_too_small_corpus():
    with pytest.raises(ValueError, match="seed_sample"):
        validate_real_only_corpus(
            [
                SimpleNamespace(record_origin="pubmed_live"),
                SimpleNamespace(record_origin="seed_sample"),
            ],
            min_live_records=1,
        )

    with pytest.raises(ValueError, match="minimum required is 2"):
        validate_real_only_corpus(
            [SimpleNamespace(record_origin="pubmed_live")], min_live_records=2
        )


def _install_sync_sentinel(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch sync_pubmed with a recorder: refusal paths must never reach it.

    哨兵兼防网络副作用：若未来校验分支被击穿，测试在调用真实 NCBI 之前就以
    AssertionError 干净变红，而不是把 live 请求发出去。
    """

    calls: list[str] = []

    def _sentinel(query: str, per_query: int):
        calls.append(query)
        raise AssertionError(f"sync_pubmed must not run in this test, got {query!r}")

    monkeypatch.setattr("app.services.literature.sync_pubmed", _sentinel)
    return calls


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "[]",
        '["atopic dermatitis", "   "]',
        '["atopic dermatitis", 123]',
    ],
    ids=["not-a-list", "empty-list", "whitespace-only-query", "non-string-query"],
)
def test_main_refuses_invalid_queries_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    payload: str,
):
    queries_file = tmp_path / "queries.json"
    queries_file.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["seed_pubmed_corpus.py", "--queries-file", str(queries_file)])
    calls = _install_sync_sentinel(monkeypatch)

    assert main() == 2
    assert "Refused to load queries-file" in capsys.readouterr().out
    assert calls == []


def test_main_loads_valid_queries_file_and_syncs_each_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    queries_file = tmp_path / "queries.json"
    queries_file.write_text('["query a", "query b"]\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["seed_pubmed_corpus.py", "--queries-file", str(queries_file)])
    calls: list[str] = []

    def _fake_sync_pubmed(query: str, per_query: int):
        calls.append(query)
        return SimpleNamespace(fetched=1, created=1, updated=0)

    monkeypatch.setattr("app.services.literature.sync_pubmed", _fake_sync_pubmed)

    assert main() == 0
    assert calls == ["query a", "query b"]
    assert "Loaded 2 queries from" in capsys.readouterr().out


def test_main_malformed_queries_json_fails_closed_with_traceback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Pins current boundary: malformed JSON crashes main() (traceback, non-zero
    exit) instead of the shape-refusal message. 若未来改为 catch 后 return 2，
    必须有意识翻转本测试——两种形态都 fail closed，契约是「不静默放行」。"""

    queries_file = tmp_path / "queries.json"
    queries_file.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["seed_pubmed_corpus.py", "--queries-file", str(queries_file)])
    _install_sync_sentinel(monkeypatch)

    with pytest.raises(json.JSONDecodeError):
        main()
