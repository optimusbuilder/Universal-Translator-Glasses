from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TranslationResult:
    window_id: int
    kind: str
    text: str
    confidence: float
    uncertain: bool
    created_at: datetime
    latency_ms: float
    source_mode: str
    retry_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "kind": self.kind,
            "text": self.text,
            "confidence": self.confidence,
            "uncertain": self.uncertain,
            "created_at": self.created_at.isoformat(),
            "latency_ms": self.latency_ms,
            "source_mode": self.source_mode,
            "retry_count": self.retry_count,
        }


@dataclass(frozen=True)
class TranslationPayload:
    text: str
    confidence: float

