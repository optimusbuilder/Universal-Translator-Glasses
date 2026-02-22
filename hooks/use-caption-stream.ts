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
  const handsDetected = toBool(
    landmark.last_frame_had_hands,
    toBool(landmark.healthy, false) && toNumber(landmark.frames_with_hands, 0) > 0
  );

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
  isProcessing: boolean;
  metrics: MetricsPayload;
  partialCaption: CaptionEntry | null;
  sessionActive: boolean;
  transcript: CaptionEntry[];
  clearTranscript: () => void;
  startSession: () => void;
  pauseSession: () => void;
};

export const useCaptionStream = ({ wsUrl }: UseCaptionStreamArgs): UseCaptionStreamResult => {
  const [sessionActive, setSessionActive] = useState(true);
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
  const reconnectAttemptRef = useRef(0);

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

  useEffect(() => {
    if (!sessionActive) {
      disconnectSocket();
      setConnectionState("disconnected");
      setIsProcessing(false);
      setPartialCaption(null);
      return;
    }

    if (!wsUrl) {
      setConnectionState("disconnected");
      setIsProcessing(false);
      setPartialCaption(null);
      addAlert({
        level: "warning",
        message: "WebSocket URL not configured.",
        timestamp: nowIso()
      });
      return;
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
  }, [addAlert, disconnectSocket, handleEvent, sessionActive, wsUrl]);

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
    isProcessing,
    metrics: stableMetrics,
    partialCaption,
    sessionActive,
    transcript,
    clearTranscript,
    startSession,
    pauseSession
  };
};
