from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class AgentResult:
    final_response: str
    trajectory: list[dict[str, Any]]
    usage: dict[str, Any]
    termination: str
    # Values are replacement text; None explicitly represents a deletion.
    delivered_patch: dict[str, str | None] | None = None

class AgentAdapter(ABC):
    @abstractmethod
    def run(self, instruction: str, workspace: Path, execute, evidence_treatment: str, model_config: dict, seed: int|None, budgets: dict) -> AgentResult: ...
