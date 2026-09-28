"""Guard the network service façade late-binding invariant.

Tests monkeypatch ``_get_repository`` / ``uuid4`` / ``select_network_provider``
on ``app.services.network`` (the façade).  Sibling modules must resolve
cross-sibling names through a function-body façade import at call time; a
module-level façade import would bind the original objects and silently
defeat every one of those patches while the suite stays green.

Enforced six ways:

1. No sibling imports the façade at module level (import cycle + bypass).
2. No sibling calls a patchable name bare instead of ``_facade.<name>``.
3. Façade patches provably reach three real sibling entry points.
4. ``app/api`` never imports the façade — the public import surface is the
   sibling modules themselves.
5. No test other than this guard imports the façade; tests patch via the
   string form ``monkeypatch.setattr("app.services.network.<name>", ...)``.
6. The façade ``__all__`` is exactly the monkeypatch surface.
"""

import ast
from pathlib import Path

from app.schemas.network import NetworkTaskRecord
from app.services import network as network_service
from app.services import network_providers, network_queries, network_tasks

SERVICES_DIR = Path(network_service.__file__).parent
PATCHABLE_NAMES = {"_get_repository", "uuid4", "select_network_provider"}


def _sibling_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(SERVICES_DIR.glob("network_*.py"))
    }


def _facade_import_offenders(source: str) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.services" and any(
                alias.name == "network" for alias in node.names
            ):
                offenders.append(f"{node.lineno}: from app.services import network")
            elif node.module == "app.services.network":
                offenders.append(f"{node.lineno}: from app.services.network import ...")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.services.network":
                    offenders.append(f"{node.lineno}: import app.services.network")
    return offenders


def test_no_sibling_imports_facade_at_module_level() -> None:
    offenders: list[str] = []
    for name, source in _sibling_sources().items():
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom):
                if node.module == "app.services" and any(
                    alias.name == "network" for alias in node.names
                ):
                    offenders.append(f"{name}:{node.lineno} from app.services import network")
                elif node.module == "app.services.network":
                    offenders.append(f"{name}:{node.lineno} from app.services.network import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "app.services.network":
                        offenders.append(f"{name}:{node.lineno} import app.services.network")
    assert offenders == [], (
        "module-level façade imports defeat monkeypatching and risk import "
        "cycles; use a function-body 'from app.services import network as "
        "_facade' instead: " + "; ".join(offenders)
    )


def test_no_bare_calls_to_patchable_names_in_siblings() -> None:
    offenders: list[str] = []
    for name, source in _sibling_sources().items():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in PATCHABLE_NAMES
            ):
                offenders.append(
                    f"{name}:{node.lineno} {node.func.id}() must be _facade.{node.func.id}()"
                )
    assert offenders == [], "bare patchable-name calls bypass façade monkeypatches: " + (
        "; ".join(offenders)
    )


def test_facade_repo_patch_reaches_query_read(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class _SentinelRepo:
        def get_owned(self, task_id: str, reviewer_id: str) -> None:
            calls.append((task_id, reviewer_id))

    monkeypatch.setattr(network_service, "_get_repository", lambda: _SentinelRepo())
    status, payload = network_queries.get_network_analysis_task("task-x", "reviewer-x")
    assert calls == [("task-x", "reviewer-x")]
    assert status == "not_found"
    assert payload is None


def test_facade_uuid4_patch_reaches_task_creation(monkeypatch) -> None:
    created: list[NetworkTaskRecord] = []

    class _StubRepo:
        def create(self, record: NetworkTaskRecord) -> bool:
            created.append(record)
            return True

    class _FixedUuid:
        hex = "bada55cafe"

    monkeypatch.setattr(network_service, "uuid4", lambda: _FixedUuid())
    accepted = network_tasks._create_queued_network_task(
        _StubRepo(),
        reviewer_id="reviewer-x",
        query="  eczema mechanism network  ",
        analysis_type="formula",
        research_protocol=None,
        disease_target_import=None,
        compound_target_import=None,
        source_task_id=None,
        data_mode="mock",
    )
    assert accepted.task_id == "network-bada55cafe"
    assert [record.task_id for record in created] == ["network-bada55cafe"]


def test_facade_provider_patch_reaches_state_machine(monkeypatch) -> None:
    real_selector = network_providers.select_network_provider
    seen: list[str] = []

    def recording_selector(data_mode: str):
        seen.append(data_mode)
        return real_selector(data_mode)

    monkeypatch.setattr(network_service, "select_network_provider", recording_selector)
    record = NetworkTaskRecord(
        task_id="network-behavioral",
        source_task_id=None,
        owner_id="reviewer-x",
        query="eczema mechanism network",
        analysis_type="formula",
        research_protocol=None,
        disease_target_import=None,
        compound_target_import=None,
        status="running",
        progress=60,
        poll_count=1,
        result=None,
        created_at="2026-09-28T00:00:00+00:00",
        data_mode="mock",
    )
    advanced = network_tasks._advance_record(record)
    assert seen == ["mock"]
    assert advanced.status == "completed"
    assert advanced.result is not None


def test_api_layer_does_not_import_facade() -> None:
    offenders: list[str] = []
    for path in sorted((SERVICES_DIR.parent / "api").glob("*.py")):
        for offender in _facade_import_offenders(path.read_text(encoding="utf-8")):
            offenders.append(f"app/api/{path.name}:{offender}")
    assert offenders == [], (
        "app/api must import network service entries from the sibling modules "
        "directly; the façade is a private late-binding patch hub, not an "
        "import surface: " + "; ".join(offenders)
    )


def test_only_the_guard_test_imports_facade() -> None:
    offenders: list[str] = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        for offender in _facade_import_offenders(path.read_text(encoding="utf-8")):
            offenders.append(f"tests/{path.name}:{offender}")
    assert offenders == [], (
        "only this guard may import the façade; patch via string form "
        'monkeypatch.setattr("app.services.network.<name>", ...) and import '
        "entry points from the sibling modules: " + "; ".join(offenders)
    )


def test_facade_all_is_exactly_the_patch_surface() -> None:
    assert sorted(network_service.__all__) == sorted(PATCHABLE_NAMES)
