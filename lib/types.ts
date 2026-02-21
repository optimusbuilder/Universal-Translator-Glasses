export type StreamEventType =
  | "caption.partial"
  | "caption.final"
  | "system.metrics"
  | "system.alert";

export type ConnectionState = "connected" | "reconnecting" | "disconnected";

export type ConfidenceLevel = "low" | "medium" | "high";

export type CaptionPayload = {
  text: string;
  timestamp: string;
  confidence: number;
};

export type MetricsPayload = {
  fps: number;
  latency_ms: number;
  hands_detected: boolean;
  queue_depth: number;
};

export type AlertLevel = "info" | "warning" | "error";

export type AlertPayload = {
  level: AlertLevel;
  message: string;
  timestamp: string;
};

export type StreamEvent =
  | { type: "caption.partial"; payload: CaptionPayload }
  | { type: "caption.final"; payload: CaptionPayload }
  | { type: "system.metrics"; payload: MetricsPayload }
  | { type: "system.alert"; payload: AlertPayload };

export type CaptionEntry = CaptionPayload & {
  id: string;
  confidenceLevel: ConfidenceLevel;
};

export type AlertEntry = AlertPayload & {
  id: string;
};

export type ReaderTab = "live" | "transcript" | "system";
export type FontScale = "small" | "medium" | "large" | "xl";
