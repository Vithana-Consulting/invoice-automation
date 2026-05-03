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

    @property
    def is_blocking(self) -> bool:
        return not self.passed and self.severity == Severity.HARD_BLOCK

class InvoiceValidator(ABC):
    code: str
    severity: Severity = Severity.HARD_BLOCK

    @abstractmethod
    def validate(self, draft, invoice, db) -> ValidationResult:
        pass

class ValidationPipeline:
    def __init__(self, validators: List[InvoiceValidator]):
        self.validators = validators

    def run(self, draft, invoice, db) -> List[ValidationResult]:
        return [v.validate(draft, invoice, db) for v in self.validators]

    @staticmethod
    def has_blocks(results: List[ValidationResult]) -> bool:
        return any(r.is_blocking for r in results)

    @staticmethod
    def blocking(results: List[ValidationResult]) -> List[ValidationResult]:
        return [r for r in results if r.is_blocking]
