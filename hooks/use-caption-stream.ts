"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  AlertEntry,
  AlertPayload,
  CaptionEntry,
  CaptionPayload,
  ConfidenceLevel,
  MetricsPayload,
  StreamEvent
} from "@/lib/types";

const MAX_TRANSCRIPT_ENTRIES = 200;
const MAX_ALERT_ENTRIES = 20;
const DEMO_PHRASES = [
  "Hello, I am glad to meet you.",
  "Can you help me find the nearest exit?",
  "Please wait one moment.",
  "I need assistance with directions.",
  "Thank you for your help."
];

const nowIso = () => new Date().toISOString();

const confidenceLevelFor = (confidence: number): ConfidenceLevel => {
  if (confidence < 0.45) {
    return "low";
  }

  if (confidence < 0.75) {
    return "medium";
  }

  return "high";
};

const captionFromPayload = (payload: CaptionPayload): CaptionEntry => ({
  ...payload,
  id: crypto.randomUUID(),
  confidenceLevel: confidenceLevelFor(payload.confidence)
});

const alertFromPayload = (payload: AlertPayload): AlertEntry => ({
  ...payload,
  id: crypto.randomUUID()
});

type BackendEventEnvelope = {
  event: string;
  timestamp?: string;
  payload?: Record<string, unknown>;
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const toNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
};

const toString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const toBool = (value: unknown, fallback = false): boolean =>
  typeof value === "boolean" ? value : fallback;

const normalizeMetricsEvent = (payload: Record<string, unknown>): StreamEvent => {
  const ingest = isObject(payload.ingest) ? payload.ingest : {};
  const landmark = isObject(payload.landmark) ? payload.landmark : {};
  const windowing = isObject(payload.windowing) ? payload.windowing : {};
  const translation = isObject(payload.translation) ? payload.translation : {};

  const fps = Math.max(0, toNumber(ingest.effective_fps, 0));
  const latencyMs = Math.max(
    0,
    toNumber(translation.last_processing_ms, toNumber(landmark.last_processing_ms, 0))
  );
  const queueDepth = Math.max(
    0,
    toNumber(landmark.queue_size, 0) +
      toNumber(windowing.queue_size, 0) +
      toNumber(translation.queue_size, 0)
  );
  const handsDetected =
    toBool(landmark.healthy, false) && toNumber(landmark.frames_with_hands, 0) > 0;

  return {
    type: "system.metrics",
    payload: {
      fps: Math.round(fps),
      latency_ms: Math.round(latencyMs),
      hands_detected: handsDetected,
      queue_depth: Math.round(queueDepth)
    }
  };
};

const normalizeAlertEvent = (
  envelopeTimestamp: string,
  payload: Record<string, unknown>
): StreamEvent => {
  const severity = toString(payload.severity, "info").toLowerCase();
  const component = toString(payload.component, "system");
  const reason = toString(payload.reason, "unknown alert");
  const level: AlertPayload["level"] =
    severity === "error" ? "error" : severity === "warning" ? "warning" : "info";

  return {
    type: "system.alert",
    payload: {
      level,
      message: `${component}: ${reason}`,
      timestamp: toString(payload.timestamp, envelopeTimestamp)
    }
  };
};

const normalizeCaptionEvent = (
  eventType: "caption.partial" | "caption.final",
  envelopeTimestamp: string,
  payload: Record<string, unknown>
): StreamEvent => {
  return {
    type: eventType,
    payload: {
      text: toString(payload.text, ""),
      timestamp: toString(payload.created_at, envelopeTimestamp),
      confidence: Math.max(0, Math.min(1, toNumber(payload.confidence, 0)))
    }
  };
};

const normalizeIncomingEvent = (raw: unknown): StreamEvent | null => {
  if (!isObject(raw)) {
    return null;
  }

  if (typeof raw.type === "string" && isObject(raw.payload)) {
    const eventType = raw.type;
    const payload = raw.payload;
    if (eventType === "caption.partial" || eventType === "caption.final") {
      return normalizeCaptionEvent(eventType, nowIso(), payload);
    }
    if (eventType === "system.metrics") {
      return normalizeMetricsEvent(payload);
    }
    if (eventType === "system.alert") {
      return normalizeAlertEvent(nowIso(), payload);
    }
    return null;
  }

  const envelope = raw as BackendEventEnvelope;
  if (typeof envelope.event !== "string" || !isObject(envelope.payload)) {
    return null;
  }

  const envelopeTimestamp = toString(envelope.timestamp, nowIso());
  if (envelope.event === "caption.partial" || envelope.event === "caption.final") {
    return normalizeCaptionEvent(envelope.event, envelopeTimestamp, envelope.payload);
  }
  if (envelope.event === "system.metrics") {
    return normalizeMetricsEvent(envelope.payload);
  }
  if (envelope.event === "system.alert") {
    return normalizeAlertEvent(envelopeTimestamp, envelope.payload);
  }

  return null;
};

type UseCaptionStreamArgs = {
  wsUrl?: string;
};

export type UseCaptionStreamResult = {
  alerts: AlertEntry[];
  connectionState: "connected" | "reconnecting" | "disconnected";
  currentCaption: CaptionEntry | null;
  demoMode: boolean;
  isProcessing: boolean;
  metrics: MetricsPayload;
  partialCaption: CaptionEntry | null;
  sessionActive: boolean;
  transcript: CaptionEntry[];
  clearTranscript: () => void;
  setDemoMode: (value: boolean) => void;
  startSession: () => void;
  pauseSession: () => void;
};

export const useCaptionStream = ({ wsUrl }: UseCaptionStreamArgs): UseCaptionStreamResult => {
  const [sessionActive, setSessionActive] = useState(false);
  const [demoMode, setDemoMode] = useState(!wsUrl);
  const [connectionState, setConnectionState] = useState<
    "connected" | "reconnecting" | "disconnected"
  >("disconnected");
  const [currentCaption, setCurrentCaption] = useState<CaptionEntry | null>(null);
  const [partialCaption, setPartialCaption] = useState<CaptionEntry | null>(null);
  const [transcript, setTranscript] = useState<CaptionEntry[]>([]);
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [metrics, setMetrics] = useState<MetricsPayload>({
    fps: 0,
    latency_ms: 0,
    hands_detected: false,
    queue_depth: 0
  });

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const demoIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const partialPhaseRef = useRef(false);
  const phraseIndexRef = useRef(0);

  const addAlert = useCallback((payload: AlertPayload) => {
    setAlerts((prev) => [alertFromPayload(payload), ...prev].slice(0, MAX_ALERT_ENTRIES));
  }, []);

  const handleEvent = useCallback(
    (event: StreamEvent) => {
      if (event.type === "caption.partial") {
        const caption = captionFromPayload(event.payload);
        setPartialCaption(caption);
        setIsProcessing(true);
        return;
      }

      if (event.type === "caption.final") {
        const caption = captionFromPayload(event.payload);
        setCurrentCaption(caption);
        setPartialCaption(null);
        setTranscript((prev) => [caption, ...prev].slice(0, MAX_TRANSCRIPT_ENTRIES));
        setIsProcessing(false);
        return;
      }

      if (event.type === "system.metrics") {
        setMetrics(event.payload);
        return;
      }

      addAlert(event.payload);
    },
    [addAlert]
  );

  const disconnectSocket = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const stopDemo = useCallback(() => {
    if (demoIntervalRef.current) {
      clearInterval(demoIntervalRef.current);
      demoIntervalRef.current = null;
    }

    partialPhaseRef.current = false;
  }, []);

  useEffect(() => {
    if (!sessionActive) {
      disconnectSocket();
      stopDemo();
      setConnectionState("disconnected");
      setIsProcessing(false);
      setPartialCaption(null);
      return;
    }

    if (demoMode || !wsUrl) {
      setConnectionState("connected");

      demoIntervalRef.current = setInterval(() => {
        const handsDetected = Math.random() > 0.08;
        const latencyMs = Math.max(1200, Math.floor(1500 + Math.random() * 800));
        const fps = Math.floor(11 + Math.random() * 5);
        const queueDepth = Math.floor(Math.random() * 3);

        handleEvent({
          type: "system.metrics",
          payload: {
            fps,
            latency_ms: latencyMs,
            hands_detected: handsDetected,
            queue_depth: queueDepth
          }
        });

        if (!handsDetected) {
          setIsProcessing(false);
          setPartialCaption(null);
          addAlert({
            level: "warning",
            message: "No hands detected.",
            timestamp: nowIso()
          });
          return;
        }

        const phrase = DEMO_PHRASES[phraseIndexRef.current % DEMO_PHRASES.length];

        if (!partialPhaseRef.current) {
          const partialText = `${phrase.slice(0, Math.floor(phrase.length * 0.6))}...`;
          handleEvent({
            type: "caption.partial",
            payload: {
              text: partialText,
              timestamp: nowIso(),
              confidence: 0.55 + Math.random() * 0.3
            }
          });
          partialPhaseRef.current = true;
          return;
        }

        handleEvent({
          type: "caption.final",
          payload: {
            text: phrase,
            timestamp: nowIso(),
            confidence: 0.6 + Math.random() * 0.35
          }
        });

        partialPhaseRef.current = false;
        phraseIndexRef.current += 1;
      }, 1300);

      return () => {
        stopDemo();
      };
    }

    let cancelled = false;

    const connect = () => {
      if (cancelled) {
        return;
      }

      setConnectionState(reconnectAttemptRef.current > 0 ? "reconnecting" : "disconnected");
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          return;
        }

        reconnectAttemptRef.current = 0;
        setConnectionState("connected");
        addAlert({
          level: "info",
          message: "Connected to caption stream.",
          timestamp: nowIso()
        });
      };

      ws.onmessage = (event) => {
        try {
          const parsed = JSON.parse(String(event.data));
          const normalized = normalizeIncomingEvent(parsed);
          if (!normalized) {
            return;
          }
          handleEvent(normalized);
        } catch {
          addAlert({
            level: "warning",
            message: "Received malformed stream payload.",
            timestamp: nowIso()
          });
        }
      };

      ws.onerror = () => {
        addAlert({
          level: "warning",
          message: "WebSocket transport error.",
          timestamp: nowIso()
        });
      };

      ws.onclose = () => {
        if (cancelled || !sessionActive) {
          return;
        }

        setConnectionState("reconnecting");
        reconnectAttemptRef.current += 1;

        const backoffMs = Math.min(10_000, reconnectAttemptRef.current * 2_000);
        reconnectTimeoutRef.current = setTimeout(connect, backoffMs);
      };
    };

    connect();

    return () => {
      cancelled = true;
      disconnectSocket();
    };
  }, [addAlert, demoMode, disconnectSocket, handleEvent, sessionActive, stopDemo, wsUrl]);

  const startSession = useCallback(() => {
    setSessionActive(true);
  }, []);

  const pauseSession = useCallback(() => {
    setSessionActive(false);
  }, []);

  const clearTranscript = useCallback(() => {
    setTranscript([]);
    setCurrentCaption(null);
    setPartialCaption(null);
    setIsProcessing(false);
  }, []);

  const stableMetrics = useMemo(() => metrics, [metrics]);

  return {
    alerts,
    connectionState,
    currentCaption,
    demoMode,
    isProcessing,
    metrics: stableMetrics,
    partialCaption,
    sessionActive,
    transcript,
    clearTranscript,
    setDemoMode,
    startSession,
    pauseSession
  };
};
