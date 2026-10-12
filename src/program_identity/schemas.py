"""Typed record shapes; persisted JSON and JSONL records carry explicit versions."""
from typing import Any, Literal, NotRequired, TypedDict

RUN_SCHEMA_VERSION = 2
COMMAND_SCHEMA_VERSION = 2
PROVENANCE_SCHEMA_VERSION = 2
EVALUATION_SCHEMA_VERSION = 2
SUMMARY_SCHEMA_VERSION = 2


class CommandRecord(TypedDict):
    schema_version: Literal[2]
    command_id: str
    command: str
    argv: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    is_test_command: bool
    observer_status: str
    module_observation: dict[str, dict[str, Any]]


class ProvenanceRecord(TypedDict):
    schema_version: Literal[2]
    event: Literal["process_start", "process_end", "module"]
    run_id: str | None
    command_id: str | None
    pid: int
    ppid: int
    interpreter: str
    cwd: str
    module: NotRequired[str]
    source_path: NotRequired[str]
    target_path: NotRequired[str]
    loaded_sha256: NotRequired[str]
    target_sha256: NotRequired[str | None]
    path_match: NotRequired[bool]
    content_match: NotRequired[bool | None]
    identity_status: NotRequired[Literal["exact_source_match", "equivalent_copy", "confirmed_content_mismatch", "unknown"]]
    instrumentation: NotRequired[str]
    error: NotRequired[str]


class ManualAnnotation(TypedDict):
    schema_version: Literal[1]
    rubric_version: str
    annotator_id: str
    rationale: str
    supporting_trajectory_refs: list[str]
    repair_completion_claim: bool
    delivered_source_tested_claim: bool
    identity_uncertainty_acknowledged: bool
    mismatch_detected: bool
    subsequent_identity_investigation_or_correction: bool
    unsupported_verification_claim: bool
    abstention_or_refusal: bool
    ambiguous_unannotated: bool
