# UI/UX Specification: Live Translation Reader

This document defines how the website should look and behave for reading real-time ASL-to-text translations.

## 1) Product Intent

The interface should feel:

1. Immediate: users can read translations without hunting for controls.
2. Calm: minimal cognitive load during live conversation.
3. Trustworthy: clear status signals when data is delayed or uncertain.

Primary use case: wearer (or companion) opens a dashboard and reads live captions while signing happens in front of camera.

## 2) Screen Structure

Single-page app with three persistent zones:

1. `Header Bar`: session identity, connection status, quick controls.
2. `Live Caption Pane` (primary focus): current rolling translation in large type.
3. `Transcript + System Panel` (secondary): past lines, metrics, and alerts.

Desktop-first split:

1. Left 70%: Live Caption Pane.
2. Right 30%: Transcript + System Panel.

Mobile/tablet:

1. Top: Header.
2. Middle: Live Caption Pane.
3. Bottom tabs: `Transcript`, `System`, `Session`.

## 3) Wireframe (Desktop)

```text
+----------------------------------------------------------------------------------+
| ASL Live Reader                  Connected ●         [Start] [Pause] [Clear]   |
| Session: Demo-01                 Camera 12 FPS       Latency 2.1s               |
+---------------------------------------------+------------------------------------+
| LIVE CAPTION                                  | TRANSCRIPT                        |
|                                               |-----------------------------------|
| "Can you help me find the nearest exit?"      | 15:04:12  Can you help me...      |
|                                               | 15:04:09  I need assistance...     |
| Partial: "Can you help me..."                 | 15:04:06  [unclear] please repeat |
|                                               |                                    |
|                                               | SYSTEM                             |
|                                               | Camera: Online                     |
|                                               | Hands Detected: Yes                |
|                                               | Inference: Healthy                 |
|                                               | Alerts: None                       |
+---------------------------------------------+------------------------------------+
```

## 4) Visual Direction

Avoid generic dashboard look. Use a strong, readable style optimized for accessibility.

### Palette

1. Background: `Slate Ink` (`#0F1720`)
2. Surface: `Graphite` (`#16212B`)
3. Primary text: `Cloud White` (`#F3F7FA`)
4. Accent: `Signal Cyan` (`#14D3C4`)
5. Warning: `Amber` (`#F2B544`)
6. Error: `Coral` (`#FF6B6B`)
7. Success: `Mint` (`#3BD38A`)

### Typography

1. Display/captions: `Sora` (bold, high legibility at large sizes).
2. UI/body: `Manrope`.
3. Metrics/timestamps: `IBM Plex Mono`.

### Shape and Depth

1. Rounded corners: medium (12px) for panels, pill chips for status.
2. Subtle gradient background, no flat single-color canvas.
3. Borders over heavy shadows for clarity in bright rooms.

## 5) Core UI Components

### A. Connection Chip

States:

1. `Connected` (green dot)
2. `Reconnecting` (amber pulse)
3. `Disconnected` (red)

### B. Live Caption Card

1. Shows most recent finalized line in very large text.
2. Shows partial line beneath in muted style.
3. Highlights low-confidence phrases with bracketed marker: `[unclear]`.

### C. Transcript Timeline

1. Chronological list with timestamps.
2. Finalized lines only by default.
3. Optional toggle to show partial history for debugging demos.

### D. Metrics Strip

Live values:

1. Ingest FPS
2. End-to-end latency
3. Hand detection confidence
4. Queue/backlog status

### E. Session Controls

1. `Start Session`
2. `Pause Stream`
3. `Clear Transcript`
4. `Export Transcript` (CSV/TXT, optional stretch)

## 6) Interaction Model

1. On page open, app auto-attempts WebSocket connection.
2. When first caption arrives, live pane animates in (short fade + slide).
3. Partial captions update in place; final caption commits to transcript.
4. On disconnect, UI never blanks out; it preserves last good caption and shows reconnection banner.
5. `Clear Transcript` requires one confirmation tap/click.

## 7) Message and State Design

Use explicit language so users know what the system is doing.

1. `No hands detected` when camera is live but no sign input is tracked.
2. `Processing...` when translation is pending.
3. `Connection lost. Reconnecting...` during transport issues.
4. `Low confidence output` when uncertainty threshold is crossed.

## 8) Accessibility Requirements

1. WCAG AA contrast minimum for all text and controls.
2. Caption font size slider (`Small`, `Medium`, `Large`, `XL`).
3. Keyboard-accessible controls and visible focus states.
4. Never rely on color alone; include icon/text for status.
5. Support reduced-motion mode (disable animation transitions).

## 9) Responsive Behavior

### Desktop (>= 1024px)

1. Two-column layout.
2. Live caption dominates visual hierarchy.
3. Transcript and metrics always visible.

### Tablet (768px - 1023px)

1. Two-column but narrower right panel.
2. Collapsible metrics module.

### Mobile (< 768px)

1. Single-column stack with sticky header.
2. Bottom segmented control for `Live`, `Transcript`, `System`.
3. Caption remains first and largest element.

## 10) Motion and Feedback

1. Caption commit animation: 150-200ms fade transition.
2. Status chip pulse only for reconnecting state.
3. Avoid constant animated backgrounds that reduce readability.

## 11) Data Contract for Frontend Rendering

UI expects backend events shaped around:

1. `caption.partial` -> `{ text, timestamp, confidence }`
2. `caption.final` -> `{ text, timestamp, confidence }`
3. `system.metrics` -> `{ fps, latency_ms, hands_detected, queue_depth }`
4. `system.alert` -> `{ level, message, timestamp }`

Frontend behavior rules:

1. Partial text updates replace current partial line.
2. Final text appends to transcript and clears partial slot.
3. Alerts are shown as non-blocking banners unless critical.

## 12) Demo Mode (Hackathon)

Add a presentable mode toggle optimized for judges:

1. Enlarged caption typography.
2. Simplified controls (only start/pause/clear visible).
3. Optional small metrics overlay to prove real-time pipeline.

## 13) Implementation Priorities (No Code Yet)

1. Build static layout skeleton and component states first.
2. Integrate WebSocket event rendering second.
3. Add accessibility controls and responsive tuning third.
4. Add polish (animations, export, theme adjustments) last.

## 14) Acceptance Criteria for UI Phase

UI phase is complete when:

1. Live captions are readable at a glance from ~1.5 meters.
2. Connection/system state is always visible and unambiguous.
3. Transcript history updates correctly from final caption events.
4. Interface remains usable on desktop and mobile.
5. Demo mode can be toggled in one click.
