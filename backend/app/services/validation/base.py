from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List

class Severity(str, Enum):
    HARD_BLOCK = "HARD_BLOCK"
    WARNING    = "WARNING"

@dataclass
class ValidationResult:
    code: str
    passed: bool
    severity: Severity
    message: str
    detail: dict = field(default_factory=dict)
    non_overridable: bool = False  # Copied from the validator that produced this result

    @property
    def is_blocking(self) -> bool:
        return not self.passed and self.severity == Severity.HARD_BLOCK

class InvoiceValidator(ABC):
    code: str
    severity: Severity = Severity.HARD_BLOCK
    non_overridable: bool = False  # If True, cannot be bypassed by any override_reason_code

    @abstractmethod
    def validate(self, draft, invoice, db) -> ValidationResult:
        pass

class ValidationPipeline:
    def __init__(self, validators: List[InvoiceValidator]):
        self.validators = validators

    def run(self, draft, invoice, db) -> List[ValidationResult]:
        results = []
        for v in self.validators:
            result = v.validate(draft, invoice, db)
            result.non_overridable = v.non_overridable
            results.append(result)
        return results

    @staticmethod
    def has_blocks(results: List[ValidationResult]) -> bool:
        return any(r.is_blocking for r in results)

    @staticmethod
    def blocking(results: List[ValidationResult]) -> List[ValidationResult]:
        return [r for r in results if r.is_blocking]

    @staticmethod
    def non_overridable_blocks(results: List[ValidationResult]) -> List[ValidationResult]:
        """Blocking results that cannot be bypassed by any override — absolute hard stops."""
        return [r for r in results if r.is_blocking and r.non_overridable]
