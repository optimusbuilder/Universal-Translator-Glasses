"use client";

import { useMemo, useState } from "react";
import { useCaptionStream } from "@/hooks/use-caption-stream";
import type { AlertEntry, CaptionEntry, FontScale, ReaderTab } from "@/lib/types";

const FONT_SCALE_CLASS: Record<FontScale, string> = {
  small: "fontScaleSmall",
  medium: "fontScaleMedium",
  large: "fontScaleLarge",
  xl: "fontScaleXl"
};

const FONT_SCALE_LABEL: Record<FontScale, string> = {
  small: "Small",
  medium: "Medium",
  large: "Large",
  xl: "XL"
};

const formatTime = (isoTimestamp: string): string => {
  const date = new Date(isoTimestamp);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

const confidenceTone = (entry: CaptionEntry | null): string => {
  if (!entry) {
    return "toneNeutral";
  }

  if (entry.confidenceLevel === "low") {
    return "toneLow";
  }

  if (entry.confidenceLevel === "medium") {
    return "toneMedium";
  }

  return "toneHigh";
};

type TranscriptPanelProps = {
  transcript: CaptionEntry[];
};

const TranscriptPanel = ({ transcript }: TranscriptPanelProps) => {
  return (
    <section className="card panel transcriptPanel" aria-label="Transcript history">
      <header className="panelHeader">
        <h2>Transcript</h2>
        <span className="monoLabel">{transcript.length} lines</span>
      </header>
      <div className="panelBody transcriptBody">
        {transcript.length === 0 ? (
          <p className="emptyState">Finalized captions will appear here.</p>
        ) : (
          <ul className="transcriptList">
            {transcript.map((entry) => (
              <li key={entry.id} className="transcriptItem">
                <time className="monoLabel">{formatTime(entry.timestamp)}</time>
                <p>{entry.text}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
};

type SystemPanelProps = {
  alerts: AlertEntry[];
  fps: number;
  handsDetected: boolean;
  latencyMs: number;
  queueDepth: number;
};

const SystemPanel = ({ alerts, fps, handsDetected, latencyMs, queueDepth }: SystemPanelProps) => {
  const inferenceState = latencyMs > 3000 ? "Degraded" : "Healthy";

  return (
    <section className="card panel systemPanel" aria-label="System status and alerts">
      <header className="panelHeader">
        <h2>System</h2>
        <span className="monoLabel">Live</span>
      </header>

      <div className="panelBody systemBody">
        <dl className="kvList">
          <div>
            <dt>Camera</dt>
            <dd>{fps > 0 ? "Online" : "Idle"}</dd>
          </div>
          <div>
            <dt>Hands Detected</dt>
            <dd>{handsDetected ? "Yes" : "No"}</dd>
          </div>
          <div>
            <dt>Inference</dt>
            <dd>{inferenceState}</dd>
          </div>
          <div>
            <dt>Queue Depth</dt>
            <dd>{queueDepth}</dd>
          </div>
        </dl>

        <div className="alertsBlock">
          <h3>Alerts</h3>
          {alerts.length === 0 ? (
            <p className="emptyState">No active alerts.</p>
          ) : (
            <ul className="alertList">
              {alerts.slice(0, 5).map((alert) => (
                <li key={alert.id} className={`alertItem alert${alert.level}`}>
                  <strong>{alert.level.toUpperCase()}</strong>
                  <p>{alert.message}</p>
                  <time className="monoLabel">{formatTime(alert.timestamp)}</time>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
};

type StatusChipProps = {
  state: "connected" | "reconnecting" | "disconnected";
};

const StatusChip = ({ state }: StatusChipProps) => {
  const label = state === "connected" ? "Connected" : state === "reconnecting" ? "Reconnecting" : "Disconnected";

  return (
    <span className={`statusChip ${state}`}>
      <span className="dot" aria-hidden="true" />
      {label}
    </span>
  );
};

export const LiveReaderApp = () => {
  const wsUrl = useMemo(() => {
    const configured = process.env.NEXT_PUBLIC_WS_URL?.trim();
    if (configured) {
      return configured;
    }

    if (typeof window === "undefined") {
      return undefined;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.hostname}:8000/ws/events`;
  }, []);

  const {
    alerts,
    connectionState,
    currentCaption,
    isProcessing,
    metrics,
    partialCaption,
    sessionActive,
    transcript,
    clearTranscript,
    pauseSession,
    startSession
  } = useCaptionStream({ wsUrl });

  const [activeTab, setActiveTab] = useState<ReaderTab>("live");
  const [fontScale, setFontScale] = useState<FontScale>("large");
  const [presenterMode, setPresenterMode] = useState(false);

  const liveStatusMessage = useMemo(() => {
    if (!sessionActive) {
      return "Session paused.";
    }

    if (!metrics.hands_detected) {
      return "No hands detected";
    }

    if (isProcessing) {
      return "Processing...";
    }

    return "Live translation running.";
  }, [isProcessing, metrics.hands_detected, sessionActive]);

  const clearWithConfirm = () => {
    const confirmed = window.confirm("Clear transcript and current captions?");
    if (confirmed) {
      clearTranscript();
    }
  };

  return (
    <div className="readerRoot">
      <header className="topBar card">
        <div className="titleBlock">
          <p className="eyebrow">ASL Live Reader</p>
          <h1>Universal Translator Glasses</h1>
          <p className="sessionMeta">Session: Live Stream</p>
        </div>

        <div className="statusBlock">
          <StatusChip state={connectionState} />
          <span className="metricChip monoLabel">Camera {metrics.fps} FPS</span>
          <span className="metricChip monoLabel">Latency {(metrics.latency_ms / 1000).toFixed(1)}s</span>
        </div>

        <div className="controlBlock" aria-label="Session controls">
          <button className="btn btnPrimary" onClick={startSession} disabled={sessionActive}>
            Start Session
          </button>
          <button className="btn" onClick={pauseSession} disabled={!sessionActive}>
            Pause Stream
          </button>
          <button className="btn btnDanger" onClick={clearWithConfirm}>
            Clear
          </button>

          <label className="toggleWrap">
            <input
              type="checkbox"
              checked={presenterMode}
              onChange={(event) => setPresenterMode(event.target.checked)}
            />
            <span>Presenter Mode</span>
          </label>
        </div>
      </header>

      <div className="fontScaleRow card" aria-label="Caption size selector">
        <span className="monoLabel">Caption Size</span>
        <div className="segmentedControl" role="radiogroup" aria-label="Caption size options">
          {(Object.keys(FONT_SCALE_LABEL) as FontScale[]).map((scale) => (
            <button
              key={scale}
              className={`segment ${scale === fontScale ? "active" : ""}`}
              onClick={() => setFontScale(scale)}
              role="radio"
              aria-checked={scale === fontScale}
            >
              {FONT_SCALE_LABEL[scale]}
            </button>
          ))}
        </div>
      </div>

      <main className={`dashboardGrid ${presenterMode ? "presenterMode" : ""}`}>
        <section className={`card liveCaptionPane ${FONT_SCALE_CLASS[fontScale]}`} aria-live="polite">
          <header className="panelHeader">
            <h2>Live Caption</h2>
            <span className={`stateText ${confidenceTone(currentCaption)}`}>{liveStatusMessage}</span>
          </header>

          <div className="captionContent">
            <p className="finalCaption">{currentCaption?.text ?? "Waiting for live translation..."}</p>
            <p className={`partialCaption ${partialCaption ? "active" : ""}`}>
              {partialCaption?.text ?? ""}
            </p>

            <div className="captionMeta">
              <span className="monoLabel">
                Confidence {currentCaption ? `${Math.round(currentCaption.confidence * 100)}%` : "--"}
              </span>
              <span className="monoLabel">Queue {metrics.queue_depth}</span>
              <span className="monoLabel">Hands {metrics.hands_detected ? "Detected" : "Not detected"}</span>
            </div>
          </div>
        </section>

        <div className="desktopColumn">
          <TranscriptPanel transcript={transcript} />
          <SystemPanel
            alerts={alerts}
            fps={metrics.fps}
            handsDetected={metrics.hands_detected}
            latencyMs={metrics.latency_ms}
            queueDepth={metrics.queue_depth}
          />
        </div>
      </main>

      <section className="mobilePanels card" aria-label="Mobile dashboard panels">
        <div className="mobileTabs" role="tablist" aria-label="Dashboard tabs">
          <button
            role="tab"
            aria-selected={activeTab === "live"}
            className={activeTab === "live" ? "active" : ""}
            onClick={() => setActiveTab("live")}
          >
            Live
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "transcript"}
            className={activeTab === "transcript" ? "active" : ""}
            onClick={() => setActiveTab("transcript")}
          >
            Transcript
          </button>
          <button
            role="tab"
            aria-selected={activeTab === "system"}
            className={activeTab === "system" ? "active" : ""}
            onClick={() => setActiveTab("system")}
          >
            System
          </button>
        </div>

        <div className="mobileTabContent">
          {activeTab === "live" && (
            <div className="mobileLive">
              <p className="mobileCaption">{currentCaption?.text ?? "Waiting for live translation..."}</p>
              <p className="mobilePartial">{partialCaption?.text ?? ""}</p>
            </div>
          )}
          {activeTab === "transcript" && <TranscriptPanel transcript={transcript} />}
          {activeTab === "system" && (
            <SystemPanel
              alerts={alerts}
              fps={metrics.fps}
              handsDetected={metrics.hands_detected}
              latencyMs={metrics.latency_ms}
              queueDepth={metrics.queue_depth}
            />
          )}
        </div>
      </section>
    </div>
  );
};
