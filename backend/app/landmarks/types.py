from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class LandmarkPoint:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class HandLandmarks:
    hand_index: int
    handedness: str
    confidence: float
    landmarks: list[LandmarkPoint]

    def to_dict(self) -> dict[str, object]:
        return {
            "hand_index": self.hand_index,
            "handedness": self.handedness,
            "confidence": self.confidence,
            "landmarks": [point.to_dict() for point in self.landmarks],
        }


@dataclass(frozen=True)
class LandmarkResult:
    frame_id: int
    source_name: str
    captured_at: datetime
    processed_at: datetime
    processing_ms: float
    hands: list[HandLandmarks]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["captured_at"] = self.captured_at.isoformat()
        payload["processed_at"] = self.processed_at.isoformat()
        payload["hands"] = [hand.to_dict() for hand in self.hands]
        return payload

