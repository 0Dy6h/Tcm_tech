"""Network pharmacology service façade (private late-binding patch hub).

The implementation lives in focused sibling modules — network_common,
network_imports, network_lineage, network_tasks, network_assembly,
network_adjudication and network_queries, plus the older network_providers,
network_connectors, network_omics, network_chembl, network_open_targets and
network_external_client.  Those sibling modules are the public import
surface: ``app.api.network`` and the test suite import from them directly.

This façade is NOT an import surface.  It exists only as the late-binding
hub that keeps the whole split call graph monkeypatch-transparent:

- Tests monkeypatch attributes on THIS module (``_get_repository``,
  ``uuid4``, ``select_network_provider``) via the string form
  ``monkeypatch.setattr("app.services.network.<name>", ...)``.
- Sibling modules resolve those names through this façade at call time
  (function-body ``from app.services import network as _facade`` late
  binding) instead of binding the original objects at import time — a
  module-level import would silently defeat the monkeypatches.
- ``__all__`` is exactly the monkeypatch surface.  The remaining re-export
  aliases below exist only so ``_facade.<name>`` keeps resolving across
  siblings; they are internal plumbing, not a public contract.

Convention, enforced by ``tests/test_network_facade_late_binding.py``:

- No sibling imports this façade at module level (import cycle plus
  monkeypatch bypass).
- The patchable names are never called bare in a sibling; they are always
  resolved as ``_facade.<name>``.
- Cross-references between split siblings also go through ``_facade.``
  (even for names outside the monkeypatch surface) so the whole call graph
  stays monkeypatch-transparent.  The one module-level exception is
  network_common: dependency-light primitives that import no sibling and
  are outside the monkeypatch surface.
- ``app/api`` never imports this façade; no test imports it either (the
  only exception is the guard test itself, which verifies this hub).
"""

from typing import TYPE_CHECKING
from uuid import uuid4

from app.repositories.runtime_storage import get_network_task_repository
from app.services.network_adjudication import (
    _adjudication_summary as _adjudication_summary,
)
from app.services.network_adjudication import (
    _latest_adjudications as _latest_adjudications,
)
from app.services.network_adjudication import (
    _lineage_row_ids as _lineage_row_ids,
)
from app.services.network_assembly import (
    _assembly_gate_projection as _assembly_gate_projection,
)
from app.services.network_imports import (
    _build_import_snapshot as _build_import_snapshot,
)
from app.services.network_imports import (
    _persist_verified_raw_artifact as _persist_verified_raw_artifact,
)
from app.services.network_imports import (
    build_verified_compound_import_snapshot as build_verified_compound_import_snapshot,
)
from app.services.network_imports import (
    build_verified_disease_import_snapshot as build_verified_disease_import_snapshot,
)
from app.services.network_lineage import (
    assess_network_research_readiness as assess_network_research_readiness,
)
from app.services.network_lineage import (
    build_target_lineage as build_target_lineage,
)
from app.services.network_lineage import (
    grade_chains_evidence as grade_chains_evidence,
)
from app.services.network_providers import select_network_provider
from app.services.network_tasks import (
    _advance_record as _advance_record,
)
from app.services.network_tasks import (
    _load_kegg_pathways as _load_kegg_pathways,
)

if TYPE_CHECKING:
    from app.repositories.protocols import NetworkTaskRepositoryProtocol

__all__ = ["_get_repository", "select_network_provider", "uuid4"]


def _get_repository() -> "NetworkTaskRepositoryProtocol":
    return get_network_task_repository()
