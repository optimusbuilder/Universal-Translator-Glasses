# Backend README: Phased Delivery + Completion Tests

This document is the backend execution plan for the ASL-to-text system.
It breaks the work into phases and defines one formal test per phase so completion is objective.

## 1) Backend Scope

Backend responsibilities:

1. Ingest camera stream from `XIAO ESP32S3 Sense`.
2. Decode frames and run hand landmark extraction (MediaPipe).
3. Buffer landmarks and call Gemini translation service.
4. Publish live events to frontend over WebSocket.
5. Provide metrics, alerts, and reliability behavior.

Out of scope:

1. Embedded firmware implementation details on the camera board.
2. Frontend UI implementation details.

## 2) Global Definition of Done (Backend)

Backend is considered done when:

1. Live camera input can flow through all backend services without manual intervention.
2. Translation events are emitted continuously with partial and final states.
3. WebSocket clients receive `caption.partial`, `caption.final`, `system.metrics`, and `system.alert`.
4. End-to-end latency stays within hackathon targets under demo conditions.

## 3) Phase Plan Overview

1. Phase 1: Service Skeleton and Environment Baseline.
2. Phase 2A: Source-Agnostic Ingest and Stability (Pre-Hardware).
3. Phase 2B: ESP32 Binding and Hardware Validation.
4. Phase 3: Frame Decode + Landmark Extraction.
5. Phase 4: Landmark Buffering and Windowing Logic.
6. Phase 5: Gemini Translation Orchestration.
7. Phase 6: WebSocket Event Broadcast Layer.
8. Phase 7: Reliability, Recovery, and Performance Hardening.
9. Phase 8: End-to-End Demo Certification.

## 4) Phase Details and Completion Tests

## Phase 1: Service Skeleton and Environment Baseline

Goal:
Establish a clean FastAPI backend structure with health endpoints, config loading, and logging baseline.

Tasks:

1. Define backend module layout and startup entrypoint.
2. Add environment/config handling for camera source, Gemini key, and runtime flags.
3. Add basic health route and structured logging format.
4. Add startup and shutdown lifecycle hooks.

Completion Test:
`P1-Backend-Boot-Test`

Test steps:

1. Start backend in local environment.
2. Call health endpoint repeatedly for 60 seconds.
3. Restart service once and call health endpoint again.

Pass criteria:

1. Health endpoint returns success response for all requests.
2. Service starts and stops without uncaught exceptions.
3. Startup/shutdown logs appear with timestamps and service version.

Artifacts to capture:

1. Health check response samples.
2. Startup/shutdown log excerpt.

## Phase 2A: Source-Agnostic Ingest and Stability (Pre-Hardware)

Goal:
Build and validate ingest reliability before ESP32 hardware is connected.

Tasks:

1. Define a source-agnostic camera ingest interface (`CameraSource` contract).
2. Implement at least one simulated source (recorded frame replay and/or local MJPEG source).
3. Handle dropped connection and automatic reconnect in ingest manager.
4. Track ingest-level metrics: FPS, reconnect count, dropped frames.
5. Emit ingest health signals for downstream consumers.

Completion Test:
`P2A-Source-Ingest-Soak-Test`

Test steps:

1. Run backend against simulated source for 10 minutes.
2. Inject one source interruption (10-20 seconds) or forced disconnect.
3. Restore source and continue stream.

Pass criteria:

1. Ingest resumes automatically after interruption.
2. No process crash during 10-minute run.
3. Effective ingest FPS remains at or above target baseline for majority of run.
4. Reconnect event is logged and counted.

Artifacts to capture:

1. Time-series ingest metrics snapshot.
2. Reconnect log lines and final reconnect count.

## Phase 2B: ESP32 Binding and Hardware Validation

Goal:
Bind ingest to live `XIAO ESP32S3 Sense` stream and verify real hardware behavior using the same reliability criteria.

Tasks:

1. Implement ESP32 camera source adapter using the real endpoint format.
2. Validate endpoint settings (resolution, cadence, reconnect behavior).
3. Re-run ingest metrics and compare against pre-hardware baseline from Phase 2A.
4. Tune ingest parameters for stable operation on real Wi-Fi conditions.

Completion Test:
`P2B-ESP32-Ingest-Soak-Test`

Test steps:

1. Run backend against live ESP32 feed for 10 minutes.
2. Introduce one temporary Wi-Fi interruption (10-20 seconds).
3. Restore network and continue stream.

Pass criteria:

1. Ingest resumes automatically after interruption without service restart.
2. No process crash during 10-minute run.
3. Effective ingest FPS remains at or above baseline target for majority of run.
4. Reconnect event is logged and counted.
5. No regressions versus Phase 2A ingest manager behavior.

Artifacts to capture:

1. ESP32 ingest metrics snapshot.
2. Reconnect log lines and final reconnect count.
3. Phase 2A vs 2B comparison note.

## Phase 3: Frame Decode + Landmark Extraction

Goal:
Decode incoming frames and extract reliable hand landmarks with MediaPipe.

Tasks:

1. Decode camera frames into processing-ready format.
2. Run MediaPipe Hands inference on eligible frames.
3. Serialize landmarks and confidence per frame.
4. Apply basic filtering for low-confidence detections.

Completion Test:
`P3-Landmark-Quality-Test`

Test steps:

1. Sign a curated list of hand poses/short signs in front of camera.
2. Record extraction outputs for a fixed 3-minute session.
3. Count frames with valid landmark sets.

Pass criteria:

1. Landmark extraction succeeds on expected signing frames.
2. Invalid/noisy detections are filtered and flagged.
3. Average extraction time per processed frame stays within target.

Artifacts to capture:

1. Landmark output sample (JSON schema-compliant).
2. Extraction latency summary.
3. Valid-detection ratio report.

## Phase 4: Landmark Buffering and Windowing Logic

Goal:
Build temporal buffering that groups landmark sequences into translation windows.

Tasks:

1. Implement rolling buffer for timestamped landmark records.
2. Generate 1-2 second windows for translation requests.
3. Ensure ordered, non-corrupted sequence output.
4. Add queue-depth and buffer-state metrics.

Completion Test:
`P4-Window-Integrity-Test`

Test steps:

1. Feed continuous landmark stream for at least 5 minutes.
2. Inspect generated windows for timing continuity.
3. Validate order and size constraints under normal and jitter conditions.

Pass criteria:

1. Windows are emitted at expected cadence.
2. No out-of-order timestamps inside a window.
3. Queue depth remains bounded without runaway growth.

Artifacts to capture:

1. Window metadata log sample.
2. Queue depth chart.
3. Timing continuity report.

## Phase 5: Gemini Translation Orchestration

Goal:
Translate landmark windows into partial and final English text via Gemini.

Tasks:

1. Build request formatter for landmark sequence payloads.
2. Implement Gemini call flow with timeout and retry policy.
3. Parse and normalize translation responses.
4. Emit confidence/uncertainty markers for low-certainty outputs.

Completion Test:
`P5-Translation-Contract-Test`

Test steps:

1. Submit known landmark-window fixtures representing known phrases.
2. Execute live calls and capture responses.
3. Validate response shape and translation readability.

Pass criteria:

1. Response contract is always valid (partial/final text with metadata).
2. Failures/timeouts produce controlled fallback behavior.
3. Curated fixtures produce recognizable outputs with acceptable latency.

Artifacts to capture:

1. Request/response contract samples.
2. Timeout/retry log evidence.
3. Fixture translation evaluation sheet.

## Phase 6: WebSocket Event Broadcast Layer

Goal:
Deliver translation and system events to frontend in real time.

Tasks:

1. Implement WebSocket connection manager.
2. Broadcast event types: `caption.partial`, `caption.final`, `system.metrics`, `system.alert`.
3. Handle client connect/disconnect lifecycle safely.
4. Provide backpressure-safe publish logic.

Completion Test:
`P6-WebSocket-Delivery-Test`

Test steps:

1. Connect one frontend client and one synthetic client listener.
2. Run signing session for 5 minutes.
3. Force one client disconnect/reconnect during session.

Pass criteria:

1. Both clients receive all required event types during active connection.
2. Reconnected client resumes receiving current stream without server restart.
3. No broadcast loop crashes or unhandled exceptions.

Artifacts to capture:

1. Event stream logs from both clients.
2. Server logs around disconnect/reconnect.

## Phase 7: Reliability, Recovery, and Performance Hardening

Goal:
Ensure backend behaves predictably under fault and load conditions.

Tasks:

1. Add fault handling for camera loss, decode errors, and Gemini timeouts.
2. Add adaptive behavior for overload (frame skipping, queue caps).
3. Expose operational metrics and alert conditions.
4. Verify graceful degradation paths.

Completion Test:
`P7-Fault-Injection-Test`

Test steps:

1. Inject camera disconnect.
2. Inject delayed translation responses.
3. Simulate burst frame load above nominal conditions.

Pass criteria:

1. Service remains running and responsive.
2. Alerts are emitted for each injected fault.
3. Recovery occurs automatically after fault removal.
4. No unbounded memory or queue growth observed.

Artifacts to capture:

1. Fault timeline with corresponding alerts.
2. Resource usage snapshot.
3. Recovery confirmation logs.

## Phase 8: End-to-End Demo Certification

Goal:
Certify backend for hackathon demo readiness.

Tasks:

1. Run full pipeline from camera ingest to UI event delivery.
2. Validate live caption cadence and stability.
3. Confirm operational checklist and fallback paths.

Completion Test:
`P8-Demo-Certification-Run`

Test steps:

1. Execute a scripted 10-minute signing session.
2. Include normal conversation pace and one intentional interruption.
3. Observe metrics and output in frontend dashboard.

Pass criteria:

1. End-to-end captions remain readable and timely through the run.
2. Interruption recovery succeeds without manual restart.
3. All critical KPIs remain within acceptable demo thresholds.
4. Team can repeat the run on demand.

Artifacts to capture:

1. KPI summary for the run.
2. Session log bundle.
3. Final go/no-go decision record.

## 5) KPI Gates Used Across Phases

1. Ingest FPS gate: target `>= 12 FPS` at baseline stream profile.
2. Landmark latency gate: target average within project threshold.
3. Translation cadence gate: updates every `1-2s`.
4. End-to-end latency gate: target `<= 3.0s`, stretch `<= 2.0s`.
5. Stability gate: no crash during 10-minute run.

## 6) Backend Testing Rhythm

1. After each phase, run that phase’s completion test before starting next phase.
2. If a phase test fails, fix and re-run until pass.
3. At end of each day, run the latest passed phase test plus a quick smoke of previous phase.

## 7) Current Status

Current state:

1. Planning complete.
2. Phase 1 implementation scaffold created.
3. Phase 1 completion test passes (validated with shortened runtime configuration).
4. Phase 2A ingest scaffold implemented with simulated source + reconnect manager.
5. Phase 2A core soak test passes with simulated source.
6. Phase 2A API-contract test passes.
7. Phase 2B dry-run scaffold implemented with ESP32 HTTP adapter + mock-based tests.
8. Phase 2B dry-run tests pass with mocked ESP32 behavior.
9. Phase 3 landmark pipeline scaffold implemented with mock extractor + API endpoints.
10. Phase 3 tests pass (`P3-Landmark-Quality-Test` and landmark API contract test).

This document is intentionally implementation-first planning only and includes no backend code.
