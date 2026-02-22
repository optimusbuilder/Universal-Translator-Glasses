from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from backend.app.ingest.sources.base import FramePacket
from backend.app.landmarks.extractors.base import HandLandmarkExtractor, LandmarkExtractorError
from backend.app.landmarks.types import HandLandmarks, LandmarkPoint


class MediaPipeHandLandmarkExtractor(HandLandmarkExtractor):
    def __init__(self, model_path: str | None = None) -> None:
        self._dependency_error: str | None = None
        self._dependency_exception: str | None = None
        self._mode: str | None = None
        self._mp: Any = None
        self._np: Any = None
        self._image_class: Any = None
        self._hands: Any = None
        self._landmarker: Any = None

        try:
            import mediapipe as mp  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
            from PIL import Image  # type: ignore[import-not-found]
        except Exception as exc:
            self._dependency_error = (
                "mediapipe extractor dependencies are missing. "
                "Install mediapipe, numpy, and Pillow to enable landmark extraction."
            )
            self._dependency_exception = str(exc)
            return

        self._mp = mp
        self._np = np
        self._image_class = Image

        solutions = getattr(mp, "solutions", None)
        if solutions is not None and hasattr(solutions, "hands"):
            try:
                self._hands = solutions.hands.Hands(
                    static_image_mode=False,
                    max_num_hands=2,
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                self._mode = "solutions"
                self._dependency_error = None
                self._dependency_exception = None
                return
            except Exception as exc:
                self._dependency_error = "mediapipe solutions initialization failed."
                self._dependency_exception = str(exc)

        tasks = getattr(mp, "tasks", None)
        vision = getattr(tasks, "vision", None) if tasks is not None else None
        base_options = getattr(tasks, "BaseOptions", None) if tasks is not None else None
        if vision is None or base_options is None:
            self._dependency_error = (
                "mediapipe tasks API is unavailable. "
                "Install a supported mediapipe package."
            )
            return

        if not model_path:
            self._dependency_error = (
                "MEDIAPIPE_HAND_MODEL_PATH is required for mediapipe tasks mode. "
                "Point it to a local hand_landmarker.task file."
            )
            return

        model_file = Path(model_path).expanduser()
        if not model_file.exists():
            self._dependency_error = (
                "mediapipe hand model file not found at MEDIAPIPE_HAND_MODEL_PATH."
            )
            self._dependency_exception = str(model_file)
            return

        try:
            options = vision.HandLandmarkerOptions(
                base_options=base_options(
                    model_asset_path=str(model_file),
                    delegate=base_options.Delegate.CPU,
                ),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=2,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._landmarker = vision.HandLandmarker.create_from_options(options)
            self._mode = "tasks"
            self._dependency_error = None
            self._dependency_exception = None
        except Exception as exc:
            self._dependency_error = "mediapipe tasks initialization failed."
            self._dependency_exception = str(exc)

    @property
    def name(self) -> str:
        return "mediapipe-hands-extractor"

    async def extract(self, frame: FramePacket) -> list[HandLandmarks]:
        if self._mode is None or self._np is None or self._image_class is None:
            reason = self._dependency_error or "mediapipe dependencies unavailable"
            if self._dependency_exception:
                reason = f"{reason} ({self._dependency_exception})"
            raise LandmarkExtractorError(reason)

        try:
            image = self._image_class.open(io.BytesIO(frame.payload)).convert("RGB")
            image_np = self._np.asarray(image)
        except Exception as exc:
            raise LandmarkExtractorError(f"frame_decode_error:{exc}") from exc

        try:
            if self._mode == "solutions":
                if self._hands is None:
                    raise LandmarkExtractorError("mediapipe solutions runtime unavailable")
                results = self._hands.process(image_np)
                return self._from_solutions(results)

            if self._mode == "tasks":
                if self._mp is None or self._landmarker is None:
                    raise LandmarkExtractorError("mediapipe tasks runtime unavailable")
                mp_image = self._mp.Image(
                    image_format=self._mp.ImageFormat.SRGB,
                    data=image_np,
                )
                results = self._landmarker.detect(mp_image)
                return self._from_tasks(results)

            raise LandmarkExtractorError("unsupported mediapipe extractor mode")
        except Exception as exc:
            raise LandmarkExtractorError(f"mediapipe_process_error:{exc}") from exc

    def _from_solutions(self, results: Any) -> list[HandLandmarks]:
        if not results or not results.multi_hand_landmarks:
            return []

        handedness_list: list[Any] = list(results.multi_handedness or [])
        output: list[HandLandmarks] = []
        for hand_index, hand_landmarks in enumerate(results.multi_hand_landmarks):
            handedness = "unknown"
            confidence = 0.0
            if hand_index < len(handedness_list):
                classified = handedness_list[hand_index].classification
                if classified:
                    handedness = str(classified[0].label).lower()
                    confidence = max(0.0, min(1.0, float(classified[0].score)))

            points: list[LandmarkPoint] = []
            for point in hand_landmarks.landmark:
                points.append(
                    LandmarkPoint(
                        x=float(point.x),
                        y=float(point.y),
                        z=float(point.z),
                    )
                )

            output.append(
                HandLandmarks(
                    hand_index=hand_index,
                    handedness=handedness,
                    confidence=confidence,
                    landmarks=points,
                )
            )

        return output

    def _from_tasks(self, results: Any) -> list[HandLandmarks]:
        hand_landmarks_list: list[Any] = list(getattr(results, "hand_landmarks", []) or [])
        handedness_list: list[Any] = list(getattr(results, "handedness", []) or [])
        if not hand_landmarks_list:
            return []

        output: list[HandLandmarks] = []
        for hand_index, hand_landmarks in enumerate(hand_landmarks_list):
            handedness = "unknown"
            confidence = 0.0
            if hand_index < len(handedness_list):
                categories = handedness_list[hand_index]
                first = categories[0] if categories else None
                if first is not None:
                    handedness = str(
                        getattr(first, "category_name", None)
                        or getattr(first, "display_name", None)
                        or "unknown"
                    ).lower()
                    confidence = max(
                        0.0,
                        min(1.0, float(getattr(first, "score", 0.0))),
                    )

            points: list[LandmarkPoint] = []
            for point in hand_landmarks:
                points.append(
                    LandmarkPoint(
                        x=float(point.x),
                        y=float(point.y),
                        z=float(point.z),
                    )
                )

            output.append(
                HandLandmarks(
                    hand_index=hand_index,
                    handedness=handedness,
                    confidence=confidence,
                    landmarks=points,
                )
            )

        return output
