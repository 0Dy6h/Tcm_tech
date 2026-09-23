import json
from datetime import UTC, date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Serialized size guard for the writer output payload of a plan consumption.
_MAX_OUTPUT_PAYLOAD_JSON_CHARS = 256 * 1024

AnalysisType = Literal["formula", "herb"]
TaskStatus = Literal["queued", "running", "completed", "failed"]
DataMode = Literal["mock", "live"]
PipelineStepStatus = Literal["completed", "failed", "skipped", "degraded"]
TargetEvidenceType = Literal["mock", "known_activity", "predicted", "mixed"]
EvidenceLevel = Literal[
    "mock_inferred",
    "predicted",
    "literature_supported",
    "omics_validated",
    "experimental",
]
DiseaseScope = Literal["atopic_dermatitis"]
ResearchSpecies = Literal["Homo sapiens"]
EvidencePolicy = Literal["direct_human_first", "mixed_exploratory"]
TargetEvidenceOrigin = Literal[
    "mock",
    "known_activity",
    "predicted",
    "mixed",
    "disease_association",
]
AutomaticExtractionStatus = Literal["extracted"]
IntersectionDerivationStatus = Literal["derived"]
AdjudicationStatus = Literal["pending", "accepted", "excluded", "needs_review"]
TargetDecision = Literal["unreviewed", "include", "exclude"]
ManualAdjudicationDecision = Literal["included", "excluded", "needs_review", "omics_confirmed"]
AssemblyGateState = Literal["blocked", "assembly_input_ready"]


class OmicsAdjudicationContext(BaseModel):
    """Client-supplied context for an omics confirmation adjudication (G3-3).

    The server re-verifies every machine condition against the frozen omics
    snapshot at adjudication time; the human confirmation is the request itself.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    accession: str = Field(min_length=3, max_length=20, pattern=r"^GSE[0-9]+$")
    canonical_symbol: str = Field(min_length=1, max_length=40)


class NetworkResearchProtocol(BaseModel):
    disease: DiseaseScope = "atopic_dermatitis"
    phenotype: str = Field(min_length=4, max_length=200)
    species: ResearchSpecies = "Homo sapiens"
    evidence_policy: EvidencePolicy
    query_date: date

    @model_validator(mode="after")
    def validate_query_date_not_in_future(self) -> Self:
        if self.query_date > date.today():
            raise ValueError("query_date cannot be in the future")
        return self


class NetworkDiseaseTargetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_identifier: str = Field(min_length=1, max_length=100)
    canonical_symbol: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[A-Z][A-Z0-9.-]*$",
    )
    source_record_id: str = Field(min_length=1, max_length=300)
    source_score: float = Field(ge=0, le=1)

    @field_validator("source_score", mode="before")
    @classmethod
    def reject_boolean_score(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("source_score must be numeric and not boolean")
        return value


class NetworkDiseaseTargetImport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_profile: Literal["open_targets_association_v1"]
    disease: DiseaseScope = "atopic_dermatitis"
    phenotype: str = Field(min_length=4, max_length=200)
    species: ResearchSpecies = "Homo sapiens"
    source_database: Literal["Open Targets Platform"]
    database_version: str = Field(min_length=1, max_length=100)
    source_query_id: str = Field(min_length=1, max_length=100)
    source_query_label: str = Field(min_length=1, max_length=200)
    source_query_parameters: dict[str, str | int | float | bool | list[str]] = Field(min_length=1)
    query_date: date
    retrieved_at: datetime
    score_name: Literal["association_score"]
    applied_threshold: float = Field(ge=0, le=1)
    threshold_operator: Literal["gte"] = "gte"
    identifier_mapping: Literal["Ensembl target approvedSymbol"]
    identifier_mapping_version: str = Field(min_length=1, max_length=100)
    records: list[NetworkDiseaseTargetRecord] = Field(default_factory=list, max_length=500)

    @field_validator("applied_threshold", mode="before")
    @classmethod
    def reject_boolean_threshold(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("applied_threshold must be numeric and not boolean")
        return value

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        if self.query_date > date.today():
            raise ValueError("disease target query_date cannot be in the future")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("disease target retrieved_at must include a timezone")
        if self.retrieved_at.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("disease target retrieved_at cannot be in the future")
        observation_keys = [
            (record.source_record_id, record.raw_identifier, record.canonical_symbol)
            for record in self.records
        ]
        if len(observation_keys) != len(set(observation_keys)):
            raise ValueError("disease target source observations must be unique")
        symbols_by_record_id: dict[str, set[str]] = {}
        for record in self.records:
            symbols_by_record_id.setdefault(record.source_record_id, set()).add(
                record.canonical_symbol
            )
        if any(len(symbols) > 1 for symbols in symbols_by_record_id.values()):
            raise ValueError("disease target source_record_id mapping is ambiguous")
        if any(record.source_score < self.applied_threshold for record in self.records):
            raise ValueError("disease target source_score must satisfy the applied threshold")
        return self


class NetworkDiseaseTargetVerifyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_profile: Literal["open_targets_association_v1"]
    disease: DiseaseScope = "atopic_dermatitis"
    phenotype: str = Field(min_length=4, max_length=200)
    species: ResearchSpecies = "Homo sapiens"
    source_database: Literal["Open Targets Platform"]
    database_version: str = Field(min_length=1, max_length=100)
    source_query_id: str = Field(min_length=1, max_length=100)
    source_query_label: str = Field(min_length=1, max_length=200)
    source_query_parameters: dict[str, str | int | float | bool | list[str]] = Field(min_length=1)
    query_date: date
    retrieved_at: datetime
    score_name: Literal["association_score"]
    applied_threshold: float = Field(ge=0, le=1)
    threshold_operator: Literal["gte"] = "gte"
    identifier_mapping: Literal["Ensembl target approvedSymbol"]
    identifier_mapping_version: str = Field(min_length=1, max_length=100)
    usage_license_note: str = Field(min_length=1, max_length=1000)

    @field_validator("applied_threshold", mode="before")
    @classmethod
    def reject_boolean_threshold(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("applied_threshold must be numeric and not boolean")
        return value

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if self.query_date > date.today():
            raise ValueError("disease target query_date cannot be in the future")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("disease target retrieved_at must include a timezone")
        if self.retrieved_at.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("disease target retrieved_at cannot be in the future")
        return self


class NetworkCompoundTargetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_identifier: str = Field(min_length=1, max_length=100, pattern=r"^CHEMBL[0-9]+$")
    canonical_symbol: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[A-Z][A-Z0-9.-]*$",
    )
    source_record_id: str = Field(min_length=1, max_length=300)
    source_score: float = Field(ge=0, le=20)

    @field_validator("source_score", mode="before")
    @classmethod
    def reject_boolean_score(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("source_score must be numeric and not boolean")
        return value


class NetworkCompoundTargetQueryParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    assay_organism: ResearchSpecies
    pchembl_value_min: float = Field(ge=0, le=20)
    standard_type: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("pchembl_value_min", mode="before")
    @classmethod
    def reject_boolean_threshold(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("pchembl_value_min must be numeric and not boolean")
        return value


class NetworkCompoundTargetVerifyMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_profile: Literal["chembl_known_activity_v1"]
    compound_id: str = Field(min_length=1, max_length=100, pattern=r"^CHEMBL[0-9]+$")
    compound_label: str = Field(min_length=1, max_length=200)
    species: ResearchSpecies = "Homo sapiens"
    source_database: Literal["ChEMBL"]
    database_version: str = Field(min_length=1, max_length=100)
    source_query_id: str = Field(min_length=1, max_length=100)
    source_query_label: str = Field(min_length=1, max_length=200)
    source_query_parameters: NetworkCompoundTargetQueryParameters
    query_date: date
    retrieved_at: datetime
    score_name: Literal["pchembl_value"]
    applied_threshold: float = Field(ge=0, le=20)
    threshold_operator: Literal["gte"] = "gte"
    identifier_mapping: Literal["ChEMBL target component gene symbol"]
    identifier_mapping_version: str = Field(min_length=1, max_length=100)
    usage_license_note: str = Field(min_length=1, max_length=1000)

    @field_validator("applied_threshold", mode="before")
    @classmethod
    def reject_boolean_threshold(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("applied_threshold must be numeric and not boolean")
        return value

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        if self.source_query_id != self.compound_id:
            raise ValueError("compound target source_query_id must match compound_id")
        if self.source_query_parameters.assay_organism != self.species:
            raise ValueError("compound target assay_organism must match species")
        if self.source_query_parameters.pchembl_value_min != self.applied_threshold:
            raise ValueError("compound target pchembl_value_min must match applied_threshold")
        if self.query_date > date.today():
            raise ValueError("compound target query_date cannot be in the future")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("compound target retrieved_at must include a timezone")
        if self.retrieved_at.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("compound target retrieved_at cannot be in the future")
        return self


class NetworkCompoundTargetImport(NetworkCompoundTargetVerifyMetadata):
    records: list[NetworkCompoundTargetRecord] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        observation_keys = [
            (record.source_record_id, record.raw_identifier, record.canonical_symbol)
            for record in self.records
        ]
        if len(observation_keys) != len(set(observation_keys)):
            raise ValueError("compound target source observations must be unique")
        source_record_ids = [record.source_record_id for record in self.records]
        if len(source_record_ids) != len(set(source_record_ids)):
            raise ValueError("compound target source_record_id values must be unique")
        if any(record.source_score < self.applied_threshold for record in self.records):
            raise ValueError("compound target source_score must satisfy the applied threshold")
        return self


class NetworkCompoundTargetVerifiedSnapshot(NetworkCompoundTargetImport):
    provenance_verification_status: Literal["server_verified_raw_artifact"]
    import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_filename: str = Field(min_length=1, max_length=255)
    source_artifact_media_type: str = Field(min_length=1, max_length=100)


NetworkCompoundTargetSnapshot = NetworkCompoundTargetVerifiedSnapshot


class NetworkCompoundTargetImportProvenance(NetworkCompoundTargetVerifyMetadata):
    record_count: int = Field(ge=0)
    provenance_verification_status: Literal["server_verified_raw_artifact"]
    import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_filename: str = Field(min_length=1, max_length=255)
    source_artifact_media_type: str = Field(min_length=1, max_length=100)


class NetworkDiseaseTargetImportSnapshot(NetworkDiseaseTargetImport):
    provenance_verification_status: Literal["unverified_client_import"]
    import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class NetworkDiseaseTargetVerifiedSnapshot(NetworkDiseaseTargetImport):
    provenance_verification_status: Literal["server_verified_raw_artifact"]
    import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_filename: str = Field(min_length=1, max_length=255)
    source_artifact_media_type: str = Field(min_length=1, max_length=100)
    usage_license_note: str = Field(min_length=1, max_length=1000)


NetworkDiseaseTargetSnapshot = (
    NetworkDiseaseTargetImportSnapshot | NetworkDiseaseTargetVerifiedSnapshot
)


class NetworkDiseaseTargetImportProvenance(BaseModel):
    source_profile: Literal["open_targets_association_v1"]
    source_database: Literal["Open Targets Platform"]
    database_version: str
    source_query_id: str
    source_query_label: str
    source_query_parameters: dict[str, str | int | float | bool | list[str]]
    query_date: date
    retrieved_at: datetime
    score_name: Literal["association_score"]
    applied_threshold: float
    threshold_operator: Literal["gte"]
    identifier_mapping: Literal["Ensembl target approvedSymbol"]
    identifier_mapping_version: str
    record_count: int = Field(ge=0)
    provenance_verification_status: Literal[
        "unverified_client_import", "server_verified_raw_artifact"
    ]
    import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_artifact_filename: str | None = None
    source_artifact_media_type: str | None = None
    usage_license_note: str | None = None

    @model_validator(mode="after")
    def validate_verified_artifact_fields(self) -> Self:
        if self.provenance_verification_status == "server_verified_raw_artifact" and any(
            not value
            for value in (
                self.source_artifact_sha256,
                self.source_artifact_filename,
                self.source_artifact_media_type,
                self.usage_license_note,
            )
        ):
            raise ValueError("server-verified provenance requires raw artifact metadata")
        return self


class NetworkResearchReadiness(BaseModel):
    protocol_complete: bool = False
    formal_network_ready: bool = False
    blocking_reasons: list[str] = Field(default_factory=lambda: ["缺少可审计的研究协议。"])


class NetworkTargetLineageRow(BaseModel):
    lineage_row_id: str | None = None
    raw_identifier: str
    canonical_symbol: str
    source_database: str
    database_version: str | None = None
    source_query: str | None = None
    query_date: date
    retrieved_at: str | None = None
    species: ResearchSpecies = "Homo sapiens"
    source_score: float | None = Field(default=None, ge=0)
    applied_threshold: float | None = Field(default=None, ge=0)
    threshold_operator: Literal["gte"] | None = None
    score_name: str | None = None
    identifier_mapping: str
    identifier_mapping_version: str | None = None
    evidence_origin: TargetEvidenceOrigin
    source_record_ids: list[str] = Field(default_factory=list)
    automatic_status: AutomaticExtractionStatus = "extracted"
    adjudication_status: AdjudicationStatus = "pending"
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    decision: TargetDecision = "unreviewed"
    decision_rationale: str | None = None


class NetworkTargetIntersectionRow(BaseModel):
    lineage_row_id: str
    canonical_symbol: str
    query_date: date
    species: ResearchSpecies = "Homo sapiens"
    derivation: Literal["canonical_symbol_exact_match_v1"] = "canonical_symbol_exact_match_v1"
    disease_lineage_row_ids: list[str] = Field(min_length=1)
    compound_lineage_row_ids: list[str] = Field(min_length=1)
    automatic_status: IntersectionDerivationStatus = "derived"
    adjudication_status: AdjudicationStatus = "pending"
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    decision: TargetDecision = "unreviewed"
    decision_rationale: str | None = None


class NetworkTargetLineage(BaseModel):
    observation_unit: Literal["target_record", "mixed"] = "mixed"
    disease_observation_unit: Literal["source_record"] = "source_record"
    compound_observation_unit: Literal["source_record"] = "source_record"
    intersection_observation_unit: Literal["canonical_symbol_derivation"] = (
        "canonical_symbol_derivation"
    )
    disease_import_provenance: NetworkDiseaseTargetImportProvenance | None = None
    compound_import_provenance: NetworkCompoundTargetImportProvenance | None = None
    disease_targets: list[NetworkTargetLineageRow] = Field(default_factory=list)
    compound_targets: list[NetworkTargetLineageRow] = Field(default_factory=list)
    intersection_targets: list[NetworkTargetIntersectionRow] = Field(default_factory=list)
    disease_target_count: int = Field(default=0, ge=0)
    compound_target_count: int = Field(default=0, ge=0)
    intersection_target_count: int = Field(default=0, ge=0)
    disease_lineage_row_count: int = Field(default=0, ge=0)
    compound_lineage_row_count: int = Field(default=0, ge=0)
    intersection_lineage_row_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)


class NetworkAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=100)
    analysis_type: AnalysisType = "formula"
    research_protocol: NetworkResearchProtocol
    disease_target_import: NetworkDiseaseTargetImport | None = None

    @model_validator(mode="after")
    def validate_disease_import_matches_protocol(self) -> Self:
        imported = self.disease_target_import
        if imported is None:
            return self
        protocol = self.research_protocol
        matching_fields = ("disease", "phenotype", "species", "query_date")
        mismatches = [
            field
            for field in matching_fields
            if getattr(imported, field) != getattr(protocol, field)
        ]
        if mismatches:
            raise ValueError(
                "disease_target_import must match research_protocol for: " + ", ".join(mismatches)
            )
        return self


class NetworkAnalyzeAccepted(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    data_mode: DataMode = "mock"


class NetworkDataSource(BaseModel):
    name: str
    source_record_id: str | None = None
    url: str | None = None
    retrieved_at: str | None = None
    license_note: str | None = None
    cache_key: str | None = None
    from_cache: bool = False


class NetworkPipelineStep(BaseModel):
    name: str
    status: PipelineStepStatus
    duration_ms: int = Field(default=0, ge=0)
    external_request_count: int = Field(default=0, ge=0)
    cache_hit_count: int = Field(default=0, ge=0)
    warning: str | None = None


class NetworkChain(BaseModel):
    herb: str
    formula: str | None = None
    compound: str
    target: str
    pathway: str
    disease: str
    score: float = Field(ge=0, le=1)
    related_entity_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    target_evidence_type: TargetEvidenceType = "mock"
    evidence_level: EvidenceLevel | None = None


class NetworkPpiEdge(BaseModel):
    source: str
    target: str
    score: float = Field(ge=0, le=1)
    source_record_id: str


class EnrichmentTerm(BaseModel):
    term_id: str
    term_name: str
    term_name_zh: str | None = None
    category: str
    gene_count: int
    overlap_count: int
    p_value: float
    adjusted_p_value: float
    genes: list[str]


class EnrichmentResult(BaseModel):
    analysis_type: str
    input_gene_count: int
    background_gene_count: int
    terms: list[EnrichmentTerm]
    timestamp: str


class NetworkAnalysisResult(BaseModel):
    task_id: str
    source_task_id: str | None = Field(default=None, pattern=r"^network-[0-9a-f]{12,32}$")
    query: str
    analysis_type: AnalysisType
    research_protocol: NetworkResearchProtocol | None = None
    readiness: NetworkResearchReadiness = Field(default_factory=NetworkResearchReadiness)
    target_lineage: NetworkTargetLineage = Field(default_factory=NetworkTargetLineage)
    data_mode: DataMode = "mock"
    chains: list[NetworkChain]
    enrichment: EnrichmentResult | None = None
    pipeline_steps: list[NetworkPipelineStep] = Field(default_factory=list)
    data_sources: list[NetworkDataSource] = Field(default_factory=list)
    ppi_edges: list[NetworkPpiEdge] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class NetworkTargetAdjudication(BaseModel):
    """One append-only manual adjudication event stored on the task record.

    ``reviewer_id`` is persisted for audit but is never projected back to any
    API response.  Adjudications are additive audit data only: they must never
    mutate the frozen target lineage rows, provenance hashes, or readiness.
    An ``omics_confirmed`` event additionally seals the omics snapshot
    accession, the confirmed canonical symbol and the DEG statistics that the
    server re-verified at adjudication time.
    """

    adjudication_id: str = Field(min_length=1, max_length=120)
    lineage_row_id: str = Field(min_length=1, max_length=120)
    decision: ManualAdjudicationDecision
    reason: str | None = Field(default=None, max_length=500)
    decided_at: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1, max_length=64)
    omics_accession: str | None = Field(default=None, min_length=3, max_length=20)
    omics_canonical_symbol: str | None = Field(default=None, min_length=1, max_length=40)
    omics_log2fc: float | None = None
    omics_adj_p_value: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_omics_confirmation_fields(self) -> Self:
        is_omics = self.decision == "omics_confirmed"
        has_omics = self.omics_accession is not None and self.omics_canonical_symbol is not None
        if is_omics and not has_omics:
            raise ValueError("omics_confirmed adjudication requires omics_accession and symbol")
        if not is_omics and has_omics:
            raise ValueError("omics fields are only valid on an omics_confirmed adjudication")
        return self


class NetworkAdjudicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    lineage_row_id: str = Field(min_length=1, max_length=120)
    decision: ManualAdjudicationDecision
    reason: str | None = Field(default=None, max_length=500)
    # Required iff decision == "omics_confirmed" (ADR-0018 Gate 3): the server
    # re-verifies every machine condition against the frozen snapshot before
    # the human confirmation is appended.
    omics: OmicsAdjudicationContext | None = None

    @field_validator("reason", mode="after")
    @classmethod
    def empty_reason_becomes_null(cls, value: str | None) -> str | None:
        if value is not None and value == "":
            return None
        return value

    @model_validator(mode="after")
    def validate_omics_context(self) -> Self:
        if (self.decision == "omics_confirmed") != (self.omics is not None):
            raise ValueError("omics context is required iff decision is omics_confirmed")
        return self


class NetworkTargetAdjudicationRecord(BaseModel):
    """API projection of one adjudication event; reviewer identity is dropped."""

    adjudication_id: str
    lineage_row_id: str
    decision: ManualAdjudicationDecision
    reason: str | None = None
    decided_at: str
    omics_accession: str | None = None
    omics_canonical_symbol: str | None = None
    omics_log2fc: float | None = None
    omics_adj_p_value: float | None = None


class NetworkAdjudicationCounts(BaseModel):
    included: int = Field(default=0, ge=0)
    excluded: int = Field(default=0, ge=0)
    needs_review: int = Field(default=0, ge=0)
    omics_confirmed: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)


class NetworkAdjudicationCurrentEntry(BaseModel):
    """Latest adjudication for one lineage row; reviewer identity is dropped."""

    lineage_row_id: str
    decision: ManualAdjudicationDecision
    reason: str | None = None
    decided_at: str


class NetworkAdjudicationSummary(BaseModel):
    """Read-only adjudication projection over the frozen target lineage."""

    counts: NetworkAdjudicationCounts = Field(default_factory=NetworkAdjudicationCounts)
    current: list[NetworkAdjudicationCurrentEntry] = Field(default_factory=list)


class NetworkAssemblyGateBlocker(BaseModel):
    code: str
    row_ids: list[str] = Field(default_factory=list)


class NetworkAssemblySelectedIntersection(BaseModel):
    lineage_row_id: str
    canonical_symbol: str
    frozen_disease_lineage_row_ids: list[str]
    frozen_compound_lineage_row_ids: list[str]
    selected_disease_lineage_row_ids: list[str] = Field(min_length=1)
    selected_compound_lineage_row_ids: list[str] = Field(min_length=1)


class NetworkAssemblyPlan(BaseModel):
    plan_id: str = Field(pattern=r"^assembly-plan-[0-9a-f]{64}$")
    policy_id: Literal["source_bound_network_assembly_v1"] = "source_bound_network_assembly_v1"
    canonicalization_id: Literal["qiyan_canonical_json_v1"] = "qiyan_canonical_json_v1"
    task_id: str
    source_task_id: str
    parent_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    child_protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    disease_source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compound_source_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    disease_import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    compound_import_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_lineage_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudication_selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_plan_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intersections: list[NetworkAssemblySelectedIntersection] = Field(min_length=1)
    plan_sequence: int = Field(ge=1)
    created_at: str
    assembly_input_ready: Literal[True] = True
    formal_network_ready: Literal[False] = False


class NetworkAssemblyPlanSummary(BaseModel):
    plan_id: str = Field(pattern=r"^assembly-plan-[0-9a-f]{64}$")
    policy_id: Literal["source_bound_network_assembly_v1"] = "source_bound_network_assembly_v1"
    canonical_plan_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_intersection_count: int = Field(ge=1)
    created_at: str
    assembly_input_ready: Literal[True] = True
    formal_network_ready: Literal[False] = False
    # D6 read-only projection: whether a writer has already consumed this plan.
    # Computed at read time; never persisted onto the frozen plan artifact.
    is_consumed: bool = False


class NetworkAssemblyConsumeRequest(BaseModel):
    """Writer request to atomically consume one candidate assembly plan.

    The writer only presents the plan handle plus its output payload; it can
    never submit hashes, readiness or adjudication fields — everything else is
    recomputed server-side inside the consume critical section. The output
    payload is opaque to this contract (the assembly computation itself is a
    later slice); it is canonicalized and hashed server-side so the D5
    idempotent replay can key on ``output_sha256`` (replay therefore assumes a
    deterministic writer output).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    writer_id: str = Field(min_length=1, max_length=64)
    canonical_plan_input_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_output_payload_size(self) -> Self:
        serialized = json.dumps(self.output_payload, ensure_ascii=False)
        if len(serialized) > _MAX_OUTPUT_PAYLOAD_JSON_CHARS:
            raise ValueError("output_payload exceeds the 256KB serialized size limit")
        return self


class NetworkAssemblyOutput(BaseModel):
    """Immutable writer output envelope (append-only assembly artifact).

    Schema-pinned: ``assembly_input_ready`` is always true and
    ``formal_network_ready`` is always false. ``chains`` and ``warnings`` are
    derived server-side from the plan's selected intersections (2026-09-11
    拍板), so they are deliberately not part of ``output_sha256`` (which keys
    the writer payload only). Consuming a plan authorizes nothing beyond the
    audit record; it never expresses scientific readiness.
    """

    output_id: str = Field(pattern=r"^assembly-output-[0-9a-f]{64}$")
    task_id: str
    source_task_id: str
    plan_id: str = Field(pattern=r"^assembly-plan-[0-9a-f]{64}$")
    plan_sequence: int = Field(ge=1)
    canonical_plan_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_id: str = Field(min_length=1, max_length=64)
    consumed_at: str
    assembly_input_ready: Literal[True] = True
    formal_network_ready: Literal[False] = False
    chains: list[NetworkChain] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str


class NetworkAssemblyConsumptionRecord(BaseModel):
    """One append-only consumption record (audit stream parallel to plan sealing).

    ``owner_id`` is persisted for owner-scoped audit exactly like the task
    record, but is never projected back to any API response.
    """

    consumption_id: str = Field(pattern=r"^assembly-consumption-[0-9a-f]{64}$")
    task_id: str
    owner_id: str
    plan_id: str = Field(pattern=r"^assembly-plan-[0-9a-f]{64}$")
    plan_sequence: int = Field(ge=1)
    canonical_plan_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_id: str = Field(pattern=r"^assembly-output-[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_id: str = Field(min_length=1, max_length=64)
    consumed_at: str


class NetworkAssemblyConsumptionProjection(BaseModel):
    """API projection of one consumption record; owner identity is dropped."""

    consumption_id: str = Field(pattern=r"^assembly-consumption-[0-9a-f]{64}$")
    plan_id: str = Field(pattern=r"^assembly-plan-[0-9a-f]{64}$")
    plan_sequence: int = Field(ge=1)
    canonical_plan_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_id: str = Field(pattern=r"^assembly-output-[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_id: str
    consumed_at: str


class NetworkAssemblyConsumeAccepted(BaseModel):
    """Response envelope for a successful plan consumption.

    ``backend_fidelity`` marks the storage boundary honestly (D7): ``preview``
    (JSON) only guarantees same-process same-instance exactly-once;
    ``production`` (SQLite) enforces it through database
    transactions and unique constraints.
    """

    state: Literal["created", "existing"]
    backend_fidelity: Literal["preview", "production"]
    output: NetworkAssemblyOutput
    consumption: NetworkAssemblyConsumptionProjection
    preview_boundaries: list[str] = Field(default_factory=list)


class NetworkAssemblyPlanAuditView(BaseModel):
    """Read-only audit projection around one historical plan (D6).

    Readable is not consumable: this view only reports whether the plan is
    still the latest revision, whether it has been consumed, and by which
    newer plan it was superseded (today the only supersede cause is a
    adjudication-stream change that re-sealed a newer plan).
    """

    plan: NetworkAssemblyPlan
    is_latest_plan: bool
    is_consumed: bool
    is_superseded_by: str | None = Field(default=None, pattern=r"^assembly-plan-[0-9a-f]{64}$")
    consumption: NetworkAssemblyConsumptionProjection | None = None


class NetworkAssemblyGateProjection(BaseModel):
    policy_id: Literal["source_bound_network_assembly_v1"] = "source_bound_network_assembly_v1"
    state: AssemblyGateState = "blocked"
    blockers: list[NetworkAssemblyGateBlocker] = Field(default_factory=list)
    latest_plan: NetworkAssemblyPlanSummary | None = None


class OmicsDegCandidate(BaseModel):
    """One lineage-matched DEG candidate awaiting manual confirmation (ADR-0018
    Gate 3). A candidate asserts nothing: it carries no evidence level and no
    decision — the only upgrade path is the append-only adjudication flow."""

    canonical_symbol: str = Field(min_length=1, max_length=40)
    lineage_row_ids: list[str] = Field(min_length=1)
    mean_case: float
    mean_control: float
    log2fc: float
    p_value: float = Field(ge=0, le=1)
    adj_p_value: float = Field(ge=0, le=1)
    status: Literal["pending_human_confirmation"] = "pending_human_confirmation"


class OmicsDegAnalysisProjection(BaseModel):
    """Deterministic DEG candidate projection (ADR-0018 Gate 3, slice G3-2).

    Pure function of the frozen omics snapshot + the task's frozen disease
    lineage: the same inputs recompute to a byte-identical projection. It is
    never written into ``NetworkAnalysisResult`` and never persisted onto
    lineage rows.
    """

    policy_id: Literal["omics_transcriptomics_deg_v1"] = "omics_transcriptomics_deg_v1"
    snapshot_id: str = Field(pattern=r"^omics-snapshot-[0-9a-f]{64}$")
    accession: str = Field(min_length=3, max_length=20, pattern=r"^GSE[0-9]+$")
    comparison: str = Field(min_length=3, max_length=200)
    case_group: str = Field(min_length=1, max_length=64)
    control_group: str = Field(min_length=1, max_length=64)
    significance_threshold: float = Field(gt=0, le=1)
    log2fc_abs_threshold: float = Field(gt=0)
    analyzed_probe_count: int = Field(ge=0)
    analyzed_gene_count: int = Field(ge=0)
    passing_gene_count: int = Field(ge=0)
    sample_groups_used: dict[str, int] = Field(min_length=1)
    symbol_mapping_rule: str = Field(min_length=1, max_length=500)
    candidates: list[OmicsDegCandidate] = Field(default_factory=list)
    formal_network_ready: Literal[False] = False


class NetworkResultResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    data_mode: DataMode = "mock"
    result: NetworkAnalysisResult | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    adjudication: NetworkAdjudicationSummary = Field(default_factory=NetworkAdjudicationSummary)
    assembly_gate: NetworkAssemblyGateProjection = Field(
        default_factory=NetworkAssemblyGateProjection
    )
    # ADR-0018 Gate 3: deterministic omics DEG candidate projection. Only
    # computed on explicit opt-in query params; never part of the default path.
    omics_verification: OmicsDegAnalysisProjection | None = Field(default=None)


class NetworkTaskSummary(BaseModel):
    """Owner-scoped task summary for list responses; never exposes owner_id."""

    task_id: str
    source_task_id: str | None = Field(default=None, pattern=r"^network-[0-9a-f]{12,32}$")
    query: str
    analysis_type: AnalysisType
    status: TaskStatus
    data_mode: DataMode = "mock"
    formal_network_ready: bool = False
    created_at: str


class NetworkTaskListResponse(BaseModel):
    tasks: list[NetworkTaskSummary] = Field(default_factory=list)


class NetworkTaskRecord(BaseModel):
    task_id: str
    source_task_id: str | None = Field(default=None, pattern=r"^network-[0-9a-f]{12,32}$")
    owner_id: str | None = None
    query: str
    analysis_type: AnalysisType
    research_protocol: NetworkResearchProtocol | None = None
    disease_target_import: NetworkDiseaseTargetSnapshot | None = None
    compound_target_import: NetworkCompoundTargetSnapshot | None = None
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    poll_count: int = Field(ge=0)
    data_mode: DataMode = "mock"
    result: NetworkAnalysisResult | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    adjudications: list[NetworkTargetAdjudication] = Field(default_factory=list)
    created_at: str

    @model_validator(mode="after")
    def validate_source_task_link(self) -> Self:
        if self.source_task_id is None:
            return self
        if self.compound_target_import is None:
            raise ValueError("source_task_id is only valid for imported compound child tasks")
        if self.source_task_id == self.task_id:
            raise ValueError("source_task_id must refer to a distinct parent task")
        return self
