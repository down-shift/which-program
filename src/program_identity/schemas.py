"""Versioned JSONL records used by the runner and evaluator."""
from typing import Any

SCHEMA_VERSION = 1

def record(kind: str, **values: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "record_type": kind, **values}
