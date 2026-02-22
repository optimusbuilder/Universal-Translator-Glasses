from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.landmarks.types import LandmarkResult


@dataclass(frozen=True)
class LandmarkWindow:
    window_id: int
    window_start: datetime
    window_end: datetime
    frame_count: int
    frames: list[LandmarkResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "window_start": self.window_start.isoformat(),
            "window_end": self.window_end.isoformat(),
            "frame_count": self.frame_count,
            "frames": [frame.to_dict() for frame in self.frames],
        }

