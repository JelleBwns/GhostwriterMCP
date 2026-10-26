import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Result(Strict):
    ok: bool = True
    data: Any = None
    error: dict[str, Any] | None = None


class DomainError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class ReportFindingContent(Strict):
    """Plain-text report content supplied by the calling agent; never generated server-side."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=512)
    severity: Severity
    description: str = Field(min_length=1, max_length=100_000)
    impact: str = Field(default="", max_length=100_000)
    remediation: str = Field(default="", max_length=100_000)
    reproduction: str = Field(default="", max_length=100_000)
    affected_entities: list[str] = Field(default_factory=list, max_length=1000)
    references: list[str] = Field(default_factory=list, max_length=100)
    finding_type_id: int | None = Field(default=None, gt=0)
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    cvss_vector: str | None = Field(default=None, max_length=512)


class ReportFindingChanges(Strict):
    """Only explicitly supplied fields are changed; scores may explicitly be cleared."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    severity: Severity | None = None
    description: str | None = Field(default=None, min_length=1, max_length=100_000)
    impact: str | None = Field(default=None, max_length=100_000)
    remediation: str | None = Field(default=None, max_length=100_000)
    reproduction: str | None = Field(default=None, max_length=100_000)
    affected_entities: list[str] | None = Field(default=None, max_length=1000)
    references: list[str] | None = Field(default=None, max_length=100)
    finding_type_id: int | None = Field(default=None, gt=0)
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    cvss_vector: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def nonempty_changes(self) -> "ReportFindingChanges":
        if not self.model_fields_set:
            raise ValueError("Supply at least one field to update")
        for field in self.model_fields_set - {"cvss_score", "cvss_vector"}:
            if getattr(self, field) is None:
                raise ValueError(f"Omit {field} instead of supplying null")
        return self


class ReportChanges(Strict):
    """Report metadata only; summary and templates have separate tools."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=512)
    complete: bool | None = None
    delivered: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def populated(self) -> "ReportChanges":
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Supply at least one metadata field; omit rather than null")
        return self


class ReportTemplateSelection(Strict):
    docx_template_id: int | None = Field(default=None, gt=0)
    pptx_template_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def populated(self) -> "ReportTemplateSelection":
        if not self.model_fields_set:
            raise ValueError(
                "Select at least one template, or explicitly null a selection to clear it"
            )
        return self
