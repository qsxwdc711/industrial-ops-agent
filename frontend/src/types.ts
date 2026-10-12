export interface Device {
  id: string;
  name: string;
  kind: "pump" | "motor";
  area: string;
  status: "normal" | "warning" | "critical" | "offline";
  temperature: number | null;
  vibration: number | null;
  current: number | null;
  pressure: number | null;
  last_seen: string | null;
  demo: number;
}
export interface Alert {
  id: string;
  device_id: string;
  metric: string;
  severity: "warning" | "critical";
  message: string;
  value: number;
  threshold: number;
  status: "open" | "acknowledged" | "resolved";
  created_at: string;
}
export interface Trend {
  bucket: string;
  temperature: number;
  vibration: number;
  samples: number;
}
export interface Telemetry {
  timestamp: string;
  temperature: number;
  vibration: number;
  current: number;
  pressure: number;
}
export interface Overview {
  devices: Device[];
  alerts: Alert[];
  trend: Trend[];
  telemetry_count: number;
  total_devices: number;
  normal_devices: number;
  open_alerts: number;
  critical_devices: number;
  shard_count: number;
  query_ms: number;
  cache_hit: boolean;
  events: Record<string, number>;
}
export interface Health {
  status: string;
  demo_data: boolean;
  llm_mode: "demo" | "ark";
  ark_configured: boolean;
  queue_backend: string;
  cache_backend: string;
  knowledge_backend: string;
  mcp_transport: string;
  shard_count: number;
  queue_depth: number;
  aggregation_error: string | null;
  simulation_enabled: boolean;
}
export interface Document {
  id: string;
  title: string;
  category: "manual" | "case" | "procedure";
  chunks: number;
  index_status: string;
  created_at: string;
  content?: string;
}
export interface Citation {
  id: string;
  document_id: string;
  title: string;
  text: string;
  position: number;
  score: number;
  retrieval: string;
}
export interface Evidence {
  tool: string;
  data: {
    source?: string;
    records?: Citation[];
    device?: Device;
    summary?: { samples: number };
  };
}
export interface AnalysisResult {
  report: string;
  evidence: Evidence[];
  mode: string;
  device_id: string;
  session_id: string;
}
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  evidence?: Evidence[];
  mode?: string;
}
export interface Session {
  id: string;
  device_id: string;
  title: string;
  created_at: string;
  messages?: ChatMessage[];
}
export interface Step {
  agent: string;
  message: string;
  tool?: string;
}
