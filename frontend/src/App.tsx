import { useCallback, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  MessageSquare,
  Plus,
  RefreshCw,
  Search,
  Send,
  Server,
  ShieldCheck,
  Sparkles,
  Square,
  Trash2,
  Waves,
  Wind,
  X,
} from "lucide-react";
import { analyze, api } from "./api";
import type {
  Alert,
  AnalysisResult,
  ChatMessage,
  Citation,
  Device,
  Document,
  Health,
  Overview,
  Session,
  Step,
  Telemetry,
} from "./types";

type Page = "overview" | "devices" | "alerts" | "knowledge" | "assistant";
const pages = [
  { id: "overview" as Page, title: "运行总览", icon: LayoutDashboard },
  { id: "devices" as Page, title: "设备管理", icon: Gauge },
  { id: "alerts" as Page, title: "监控告警", icon: Bell },
  { id: "knowledge" as Page, title: "运维知识库", icon: BookOpen },
  { id: "assistant" as Page, title: "智能运维助手", icon: Sparkles },
];
const statusLabels = {
  normal: "运行正常",
  warning: "需要关注",
  critical: "严重异常",
  offline: "等待采样",
};
const categories = {
  manual: "设备手册",
  case: "故障案例",
  procedure: "操作规程",
};
const number = (value: number) => new Intl.NumberFormat("zh-CN").format(value);
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
const shortHour = (value: string) =>
  new Date(value).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

function Badge({ status }: { status: Device["status"] }) {
  return (
    <span className={`badge ${status}`}>
      <span className="dot" />
      {statusLabels[status]}
    </span>
  );
}

function Chart({
  values,
  labels,
  unit = "°C",
  color = "#258a70",
  compact = false,
}: {
  values: number[];
  labels?: string[];
  unit?: string;
  color?: string;
  compact?: boolean;
}) {
  if (values.length < 2)
    return <div className="empty small">暂无足够的趋势数据</div>;
  const width = 680,
    height = compact ? 64 : 225,
    pad = compact ? 3 : 28;
  const low = Math.min(...values) - (compact ? 1 : 3),
    high = Math.max(...values) + (compact ? 1 : 3);
  const points = values.map(
    (value, i) =>
      `${pad + (i * (width - pad * 2)) / (values.length - 1)},${height - pad - ((value - low) / (high - low)) * (height - pad * 2)}`,
  );
  const path = `M${points.join(" L")}`;
  return (
    <div className={compact ? "sparkline" : "chart"}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio={compact ? "none" : "xMidYMid meet"}
        role="img"
        aria-label={`设备趋势，单位 ${unit}`}
      >
        <defs>
          <linearGradient
            id={`fill-${color.replace("#", "")}-${compact}`}
            x1="0"
            x2="0"
            y1="0"
            y2="1"
          >
            <stop offset="0%" stopColor={color} stopOpacity=".15" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {!compact &&
          [0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line
                x1={pad}
                y1={pad + (i * (height - pad * 2)) / 3}
                x2={width - pad}
                y2={pad + (i * (height - pad * 2)) / 3}
                stroke="#e8edf1"
                strokeDasharray="4 5"
              />
              <text
                x="0"
                y={pad + (i * (height - pad * 2)) / 3 + 4}
                fill="#9aa5b3"
                fontSize="10"
              >
                {(high - (i * (high - low)) / 3).toFixed(0)}
              </text>
            </g>
          ))}
        <path
          d={`${path} L${width - pad},${height - pad} L${pad},${height - pad} Z`}
          fill={`url(#fill-${color.replace("#", "")}-${compact})`}
        />
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth={compact ? 2 : 2.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      {!compact && labels && (
        <div className="chart-labels">
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
            <span key={ratio}>
              {labels[Math.round((labels.length - 1) * ratio)]}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-heading">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("overview");
  const [overview, setOverview] = useState<Overview>();
  const [health, setHealth] = useState<Health>();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [alertFilter, setAlertFilter] = useState("all");
  const [metric, setMetric] = useState<"temperature" | "vibration">(
    "temperature",
  );
  const [selectedDevice, setSelectedDevice] = useState<Device>();
  const [history, setHistory] = useState<Telemetry[]>([]);
  const [viewDocument, setViewDocument] = useState<Document>();
  const [importOpen, setImportOpen] = useState(false);
  const [docTitle, setDocTitle] = useState("");
  const [docCategory, setDocCategory] =
    useState<Document["category"]>("manual");
  const [docContent, setDocContent] = useState("");
  const [saving, setSaving] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [registration, setRegistration] = useState<
    Pick<Device, "id" | "name" | "kind" | "area">
  >({ id: "", name: "", kind: "pump", area: "" });
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [results, setResults] = useState<Citation[] | null>(null);
  const [deviceId, setDeviceId] = useState("P-101");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<string>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const controller = useRef<AbortController | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const currentPage = pages.find((item) => item.id === page)!;

  const refresh = useCallback(async () => {
    try {
      const [nextOverview, nextHealth, nextDocuments] = await Promise.all([
        api<Overview>("/overview"),
        api<Health>("/health"),
        api<Document[]>("/knowledge"),
      ]);
      setOverview(nextOverview);
      setHealth(nextHealth);
      setDocuments(nextDocuments);
    } catch (error) {
      setNotice((error as Error).message + "。请确认后端服务已启动。");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (notice) {
      const timer = setTimeout(() => setNotice(""), 6500);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  useEffect(() => {
    if (page === "assistant")
      api<Session[]>("/sessions")
        .then(setSessions)
        .catch((error) => setNotice(error.message));
  }, [page]);
  useEffect(() => {
    if (busy || messages.length)
      chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, streamText, busy]);
  useEffect(() => () => controller.current?.abort(), []);

  function navigate(next: Page) {
    setPage(next);
    setSearch("");
  }
  function startChat(id?: string) {
    if (busy) {
      setNotice("请先等待当前分析完成，或停止分析。");
      return;
    }
    if (id) setDeviceId(id);
    setSessionId(undefined);
    setMessages([]);
    setSteps([]);
    setStreamText("");
    setQuestion("");
    navigate("assistant");
  }
  async function showDevice(device: Device) {
    setSelectedDevice(device);
    setHistory([]);
    try {
      setHistory(await api<Telemetry[]>(`/devices/${device.id}/telemetry`));
    } catch (error) {
      setNotice((error as Error).message);
    }
  }
  async function acknowledge(alert: Alert) {
    try {
      await api(`/alerts/${alert.id}/acknowledge`, "POST");
      await refresh();
      setNotice("告警已确认，异常原因仍需进一步检查。");
    } catch (error) {
      setNotice((error as Error).message);
    }
  }
  async function importDocument() {
    setSaving(true);
    try {
      await api("/knowledge", "POST", {
        title: docTitle,
        category: docCategory,
        content: docContent,
      });
      setImportOpen(false);
      setDocTitle("");
      setDocContent("");
      await refresh();
      setNotice("文档已导入，知识索引已更新。");
    } catch (error) {
      setNotice((error as Error).message);
      await refresh();
    } finally {
      setSaving(false);
    }
  }
  async function sendQuestion(text = question) {
    if (busy || text.trim().length < 2) return;
    setBusy(true);
    setQuestion("");
    setSteps([]);
    setStreamText("");
    setMessages((previous) => [...previous, { role: "user", content: text }]);
    const abort = new AbortController();
    controller.current = abort;
    try {
      await analyze(
        { question: text, device_id: deviceId, session_id: sessionId },
        (event, data) => {
          if (event === "session")
            setSessionId(String((data as Record<string, unknown>).session_id));
          if (event === "step")
            setSteps((previous) => [...previous, data as unknown as Step]);
          if (event === "token")
            setStreamText(
              (previous) =>
                previous + String((data as Record<string, unknown>).text),
            );
          if (event === "result") {
            const result = data as AnalysisResult;
            setStreamText("");
            setMessages((previous) => [
              ...previous,
              {
                role: "assistant",
                content: result.report,
                evidence: result.evidence,
                mode: result.mode,
              },
            ]);
          }
        },
        abort.signal,
      );
      setSessions(await api<Session[]>("/sessions"));
    } catch (error) {
      setNotice(
        abort.signal.aborted ? "分析已停止。" : (error as Error).message,
      );
      setStreamText("");
    } finally {
      setBusy(false);
      controller.current = null;
    }
  }
  async function loadSession(session: Session) {
    if (busy) return;
    try {
      const detail = await api<Session>(`/sessions/${session.id}`);
      setSessionId(detail.id);
      setDeviceId(detail.device_id);
      setMessages(detail.messages || []);
      setSteps([]);
      setStreamText("");
    } catch (error) {
      setNotice((error as Error).message);
    }
  }

  const devices = overview?.devices || [];
  const alerts = overview?.alerts || [];
  const abnormal = devices
    .filter(
      (device) => device.status === "warning" || device.status === "critical",
    )
    .sort(
      (a, b) =>
        (a.status === "critical" ? -1 : 1) - (b.status === "critical" ? -1 : 1),
    );
  const filteredDevices = devices.filter(
    (device) =>
      (kind === "all" || device.kind === kind) &&
      `${device.id}${device.name}${device.area}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const filteredAlerts = alerts.filter(
    (alert) =>
      (alertFilter === "all" || alert.status === alertFilter) &&
      `${alert.device_id}${alert.message}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const latest = devices
    .map((device) => device.last_seen)
    .filter((value): value is string => !!value)
    .sort()
    .at(-1);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Activity size={23} />
          </div>
          <div>
            <strong>
              智维<span> · </span>工业运维
            </strong>
            <small>INDUSTRIAL OPERATIONS</small>
          </div>
        </div>
        <div className="workspace-switch">
          <span className="workspace-icon">
            <Wind size={19} />
          </span>
          <div>
            <strong>旋转设备运维中心</strong>
            <small>水泵与电机 · 演示场景</small>
          </div>
          <ChevronDown size={15} />
        </div>
        <div className="nav-caption">工作空间</div>
        <nav aria-label="主导航">
          {pages.map((item) => (
            <button
              key={item.id}
              aria-label={item.title}
              title={item.title}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={19} />
              <span>{item.title}</span>
              {item.id === "alerts" && !!overview?.open_alerts && (
                <em>{overview.open_alerts}</em>
              )}
              {item.id === "assistant" && <span className="ai-label">AI</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connection-card">
            <div>
              <span className={`dot ${health ? "green" : "gray"}`} />
              <strong>{health ? "数据服务已连接" : "等待数据服务"}</strong>
            </div>
            <small>
              {health?.llm_mode === "ark"
                ? health.ark_configured
                  ? "火山方舟模型已配置"
                  : "方舟模型等待配置"
                : "当前为规则演示模式"}
            </small>
            <button onClick={() => startChat()}>
              打开运维助手 <ArrowUpRight size={14} />
            </button>
          </div>
          <div className="profile">
            <div className="avatar">运</div>
            <div>
              <strong>运维工作台</strong>
              <small>本地开发环境</small>
            </div>
            <ShieldCheck size={17} />
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            工作空间 <ChevronRight size={14} />
            <strong>{currentPage.title}</strong>
          </div>
          <div className="topbar-right">
            <span className="environment">
              <span className="dot amber" />
              {health?.demo_data
                ? "演示数据"
                : health
                  ? "设备数据"
                  : "正在连接"}
            </span>
            <button
              className="icon-button"
              aria-label="查看告警"
              onClick={() => navigate("alerts")}
            >
              <Bell size={19} />
              {!!overview?.open_alerts && <span className="notification-dot" />}
            </button>
            <div className="avatar small">运</div>
          </div>
        </header>
        <div
          className={`page-content ${page === "assistant" ? "assistant-page" : ""}`}
        >
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {page === "overview"
                  ? "OPERATIONS AT A GLANCE"
                  : "INDUSTRIAL WORKSPACE"}
              </div>
              <h1>{currentPage.title}</h1>
              <p>
                {
                  {
                    overview:
                      "从设备状态到故障线索，让每一次运维决策都有依据。",
                    devices: "查看水泵与电机状态，追踪关键运行指标。",
                    alerts: "及时发现异常，保留每一次告警与处置记录。",
                    knowledge: "让分散的设备手册和运维经验，成为可检索的知识。",
                    assistant: "关联设备数据与运维知识，逐步分析你的问题。",
                  }[page]
                }
              </p>
            </div>
            <div className="heading-actions">
              {page === "devices" && (
                <button
                  className="button"
                  onClick={() => setRegisterOpen(true)}
                >
                  <Plus size={15} />
                  添加设备
                </button>
              )}
              {page === "knowledge" ? (
                <button
                  className="button primary"
                  onClick={() => setImportOpen(true)}
                >
                  <Plus size={17} />
                  导入文档
                </button>
              ) : (
                page !== "assistant" && (
                  <>
                    <button className="button" onClick={() => void refresh()}>
                      <RefreshCw size={15} />
                      刷新数据
                    </button>
                    <button
                      className="button primary"
                      onClick={() => startChat(abnormal[0]?.id)}
                    >
                      <Sparkles size={16} />
                      智能诊断
                    </button>
                  </>
                )
              )}
            </div>
          </div>
          {loading ? (
            <div className="empty">
              <LoaderCircle className="spin" size={28} />
              <p>正在连接设备数据服务…</p>
            </div>
          ) : !overview ? (
            <div className="empty">
              <Server size={32} />
              <h3>数据服务尚未连接</h3>
              <p>启动 Python 后端后，点击刷新重试。</p>
              <button className="button" onClick={() => void refresh()}>
                重新连接
              </button>
            </div>
          ) : (
            <>
              {page === "overview" && (
                <>
                  <div className="welcome-strip">
                    <div>
                      <span className="dot green" />
                      <strong>设备数据已同步</strong>
                      <span>
                        {latest ? `最近采集 ${time(latest)}` : "等待设备采样"}
                      </span>
                    </div>
                    <span>
                      <Clock3 size={14} />每 30 秒刷新视图
                    </span>
                  </div>
                  <div className="stats-grid">
                    {[
                      {
                        label: "接入设备",
                        value: overview.total_devices,
                        unit: "台",
                        detail: "覆盖水泵与驱动电机",
                        icon: Gauge,
                        tone: "blue",
                      },
                      {
                        label: "正常运行",
                        value: overview.normal_devices,
                        unit: "台",
                        detail: `${((overview.normal_devices / Math.max(1, overview.total_devices)) * 100).toFixed(1)}% 设备状态正常`,
                        icon: CheckCircle2,
                        tone: "green",
                      },
                      {
                        label: "待确认告警",
                        value: overview.open_alerts,
                        unit: "条",
                        detail: `${overview.critical_devices} 台设备存在严重异常`,
                        icon: Bell,
                        tone: "orange",
                      },
                      {
                        label: "累计采集数据",
                        value: overview.telemetry_count,
                        unit: "条",
                        detail: `分布在 ${overview.shard_count} 张设备数据表`,
                        icon: Database,
                        tone: "purple",
                      },
                    ].map((item) => (
                      <section
                        className={`card stat-card ${item.tone}`}
                        key={item.label}
                      >
                        <div className="stat-top">
                          <span>{item.label}</span>
                          <div className="stat-icon">
                            <item.icon size={19} />
                          </div>
                        </div>
                        <div className="stat-value">
                          {number(item.value)}
                          <span>{item.unit}</span>
                        </div>
                        <div className="stat-detail">
                          <span className="dot" />
                          {item.detail}
                        </div>
                      </section>
                    ))}
                  </div>
                  <div className="dashboard-grid">
                    <section className="card trend-card">
                      <div className="section-heading">
                        <div>
                          <h2>设备运行趋势</h2>
                          <p>最近 24 小时 · 全部设备小时平均值</p>
                        </div>
                        <div className="segmented">
                          <button
                            className={
                              metric === "temperature" ? "selected" : ""
                            }
                            onClick={() => setMetric("temperature")}
                          >
                            温度
                          </button>
                          <button
                            className={metric === "vibration" ? "selected" : ""}
                            onClick={() => setMetric("vibration")}
                          >
                            振动
                          </button>
                        </div>
                      </div>
                      <div className="chart-meta">
                        <span className="dot green" />
                        {metric === "temperature" ? "平均温度" : "平均振动"}
                        <small>
                          {metric === "temperature" ? "单位 °C" : "单位 mm/s"}
                        </small>
                      </div>
                      <Chart
                        values={overview.trend.map((row) => row[metric])}
                        labels={overview.trend.map((row) =>
                          shortHour(row.bucket),
                        )}
                        unit={metric === "temperature" ? "°C" : "mm/s"}
                      />
                      <div className="chart-footer">
                        <Activity size={14} />
                        基于已入库数据聚合
                        <span>{overview.trend.length} 个小时窗口</span>
                      </div>
                    </section>
                    <section className="card attention-card">
                      <div className="section-heading">
                        <div>
                          <h2>
                            需要关注的设备{" "}
                            <span className="count-pill">
                              {abnormal.length}
                            </span>
                          </h2>
                          <p>优先查看异常设备的运行证据</p>
                        </div>
                        <Bell size={18} className="muted" />
                      </div>
                      {abnormal.length ? (
                        abnormal.slice(0, 3).map((device) => (
                          <div className="attention-device" key={device.id}>
                            <div className={`device-icon ${device.status}`}>
                              <Waves size={20} />
                            </div>
                            <div>
                              <strong>{device.name}</strong>
                              <small>
                                {device.id} · {device.area}
                              </small>
                              <Badge status={device.status} />
                            </div>
                            <button
                              className="icon-button"
                              aria-label={`分析 ${device.id}`}
                              onClick={() => startChat(device.id)}
                            >
                              <ArrowUpRight size={18} />
                            </button>
                          </div>
                        ))
                      ) : (
                        <div className="empty small">当前设备状态正常</div>
                      )}
                      <button
                        className="text-button full"
                        onClick={() => navigate("devices")}
                      >
                        查看全部设备 <ArrowRight size={15} />
                      </button>
                    </section>
                  </div>
                  <div className="lower-grid">
                    <section className="card">
                      <div className="section-heading">
                        <div>
                          <h2>最新告警</h2>
                          <p>从异常信号开始，定位需要处理的问题</p>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => navigate("alerts")}
                        >
                          全部告警 <ArrowRight size={14} />
                        </button>
                      </div>
                      <div className="compact-alerts">
                        {alerts.slice(0, 3).map((alert) => (
                          <div className="compact-alert" key={alert.id}>
                            <span
                              className={`severity-marker ${alert.severity}`}
                            />
                            <div>
                              <strong>
                                {alert.device_id} ·{" "}
                                {alert.metric === "temperature"
                                  ? "温度异常"
                                  : "振动异常"}
                              </strong>
                              <small>{alert.message}</small>
                            </div>
                            <span className="alert-time">
                              {time(alert.created_at)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </section>
                    <section className="assistant-promo">
                      <div className="promo-icon">
                        <Sparkles size={22} />
                      </div>
                      <span className="eyebrow">YOUR OPERATIONS COPILOT</span>
                      <h2>让数据，成为诊断线索。</h2>
                      <p>
                        联合设备指标、告警、日志与知识库，
                        <br />
                        给出有证据的分析与检查建议。
                      </p>
                      <button onClick={() => startChat(abnormal[0]?.id)}>
                        开始一次分析 <ArrowRight size={17} />
                      </button>
                      <div className="promo-orbit" />
                    </section>
                  </div>
                  <div className="data-strip">
                    <div>
                      <Server size={16} />
                      <strong>当前服务状态</strong>
                      <span className="dot green" />
                      运行中
                    </div>
                    <span>
                      待处理事件 <b>{health?.queue_depth || 0}</b>
                    </span>
                    <span>
                      知识文档 <b>{documents.length}</b>
                    </span>
                    <span>
                      本次查询 <b>{overview.query_ms} ms</b>
                      {overview.cache_hit ? " · 缓存命中" : ""}
                    </span>
                  </div>
                </>
              )}
              {page === "devices" && (
                <section className="card table-card">
                  <div className="table-toolbar">
                    <div className="tabs">
                      {[
                        ["all", "全部设备"],
                        ["pump", "水泵"],
                        ["motor", "电机"],
                      ].map(([id, label]) => (
                        <button
                          key={id}
                          className={kind === id ? "selected" : ""}
                          onClick={() => setKind(id)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <label className="search-input">
                      <Search size={16} />
                      <input
                        placeholder="搜索设备名称、编号或区域"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </label>
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>设备信息</th>
                          <th>所属区域</th>
                          <th>运行状态</th>
                          <th>温度 / °C</th>
                          <th>振动 / mm/s</th>
                          <th>最近采集</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredDevices.map((device) => (
                          <tr key={device.id}>
                            <td>
                              <div className="device-cell">
                                <span className="device-icon">
                                  <Waves size={19} />
                                </span>
                                <div>
                                  <strong>{device.name}</strong>
                                  <small>
                                    {device.id} ·{" "}
                                    {device.kind === "pump" ? "水泵" : "电机"}
                                  </small>
                                </div>
                              </div>
                            </td>
                            <td>{device.area}</td>
                            <td>
                              <Badge status={device.status} />
                            </td>
                            <td
                              className={
                                (device.temperature ?? 0) >= 70
                                  ? "abnormal-value"
                                  : ""
                              }
                            >
                              {device.temperature?.toFixed(1) ?? "—"}
                            </td>
                            <td
                              className={
                                (device.vibration ?? 0) >= 4.5
                                  ? "abnormal-value"
                                  : ""
                              }
                            >
                              {device.vibration?.toFixed(2) ?? "—"}
                            </td>
                            <td className="muted">
                              {device.last_seen
                                ? time(device.last_seen)
                                : "暂无采样"}
                            </td>
                            <td>
                              <button
                                className="text-button"
                                onClick={() => void showDevice(device)}
                              >
                                详情
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!filteredDevices.length && (
                    <div className="empty small">没有匹配的设备</div>
                  )}
                  <div className="table-footer">
                    共 {filteredDevices.length} 台设备
                    <span>设备阈值为场景演示配置</span>
                  </div>
                </section>
              )}
              {page === "alerts" && (
                <section className="card table-card">
                  <div className="table-toolbar">
                    <div className="tabs">
                      {[
                        ["all", "全部告警"],
                        ["open", "待确认"],
                        ["acknowledged", "已确认"],
                      ].map(([id, label]) => (
                        <button
                          key={id}
                          className={alertFilter === id ? "selected" : ""}
                          onClick={() => setAlertFilter(id)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                    <label className="search-input">
                      <Search size={16} />
                      <input
                        placeholder="搜索设备编号或告警内容"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </label>
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>告警级别</th>
                          <th>设备</th>
                          <th>告警内容</th>
                          <th>测量值 / 阈值</th>
                          <th>产生时间</th>
                          <th>处置状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredAlerts.map((alert) => (
                          <tr key={alert.id}>
                            <td>
                              <span className={`badge ${alert.severity}`}>
                                <span className="dot" />
                                {alert.severity === "critical"
                                  ? "严重"
                                  : "提醒"}
                              </span>
                            </td>
                            <td>
                              <strong>{alert.device_id}</strong>
                            </td>
                            <td>{alert.message}</td>
                            <td>
                              <strong className="abnormal-value">
                                {alert.value}
                              </strong>
                              <span className="muted">
                                {" "}
                                / {alert.threshold}
                              </span>
                            </td>
                            <td className="muted">{time(alert.created_at)}</td>
                            <td>
                              {alert.status === "open" ? (
                                <span className="pending-label">待确认</span>
                              ) : (
                                <span className="ack-label">
                                  <Check size={13} />
                                  已确认
                                </span>
                              )}
                            </td>
                            <td>
                              <div className="row-actions">
                                {alert.status === "open" && (
                                  <button
                                    className="text-button"
                                    onClick={() => void acknowledge(alert)}
                                  >
                                    确认
                                  </button>
                                )}
                                <button
                                  className="text-button"
                                  onClick={() => startChat(alert.device_id)}
                                >
                                  分析
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!filteredAlerts.length && (
                    <div className="empty small">当前没有匹配的告警</div>
                  )}
                  <div className="table-footer">
                    共 {filteredAlerts.length} 条告警
                    <span>确认表示已关注，设备运行状态由最新指标决定</span>
                  </div>
                </section>
              )}
              {page === "knowledge" && (
                <>
                  <div className="knowledge-banner">
                    <div className="knowledge-banner-icon">
                      <BookOpen size={24} />
                    </div>
                    <div>
                      <h3>让每份经验，都能被找到</h3>
                      <p>设备手册、故障案例与操作规程，保留原文与片段来源。</p>
                    </div>
                    <span className="outline-badge">
                      {health?.knowledge_backend === "milvus"
                        ? "Milvus 向量检索"
                        : "本地关键词检索"}
                    </span>
                  </div>
                  <form
                    className="knowledge-search"
                    onSubmit={(event) => {
                      event.preventDefault();
                      api<Citation[]>(
                        `/knowledge/search?q=${encodeURIComponent(knowledgeQuery)}`,
                      )
                        .then(setResults)
                        .catch((error) => setNotice(error.message));
                    }}
                  >
                    <Search size={19} />
                    <input
                      placeholder="输入故障现象，例如：水泵轴承温升与振动异常"
                      value={knowledgeQuery}
                      onChange={(event) =>
                        setKnowledgeQuery(event.target.value)
                      }
                    />
                    <button
                      className="button primary"
                      disabled={knowledgeQuery.trim().length < 2}
                    >
                      检索知识
                    </button>
                  </form>
                  {results !== null && (
                    <section className="card search-results">
                      <div className="section-heading">
                        <h2>检索结果 · {results.length} 个片段</h2>
                        <button
                          className="text-button"
                          onClick={() => setResults(null)}
                        >
                          收起
                        </button>
                      </div>
                      {results.length ? (
                        results.map((result) => (
                          <div className="citation" key={result.id}>
                            <strong>{result.title}</strong>
                            <small>
                              片段 {result.position + 1} ·{" "}
                              {result.retrieval === "keyword"
                                ? "关键词匹配"
                                : "向量相似度"}{" "}
                              {result.score.toFixed(2)}
                            </small>
                            <p>{result.text}</p>
                          </div>
                        ))
                      ) : (
                        <p className="muted">
                          未找到相关片段。可以导入对应设备手册后再次检索。
                        </p>
                      )}
                    </section>
                  )}
                  <div className="section-heading document-list-heading">
                    <h2>
                      知识文档{" "}
                      <span className="count-pill">{documents.length}</span>
                    </h2>
                    <small className="muted">
                      支持导入 .txt、.md 或直接粘贴文本
                    </small>
                  </div>
                  <div className="document-grid">
                    {documents.map((doc) => (
                      <section className="card document-card" key={doc.id}>
                        <div className="document-top">
                          <span className="document-icon">
                            <FileText size={24} />
                          </span>
                          <button
                            className="icon-button"
                            aria-label={`删除 ${doc.title}`}
                            onClick={async () => {
                              if (
                                !window.confirm(
                                  `删除“${doc.title}”及其知识片段？`,
                                )
                              )
                                return;
                              try {
                                await api(`/knowledge/${doc.id}`, "DELETE");
                                await refresh();
                              } catch (error) {
                                setNotice((error as Error).message);
                              }
                            }}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                        <span className="document-category">
                          {categories[doc.category]}
                        </span>
                        <h3>{doc.title}</h3>
                        <div className="document-meta">
                          <span>{doc.chunks} 个知识片段</span>
                          <span
                            className={`dot ${doc.index_status === "failed" ? "red" : "green"}`}
                          />
                          {doc.index_status === "failed"
                            ? "索引失败"
                            : doc.index_status === "milvus"
                              ? "向量索引"
                              : "本地索引"}
                        </div>
                        <div className="document-bottom">
                          <small>{time(doc.created_at)}</small>
                          <button
                            className="text-button"
                            onClick={() =>
                              api<Document>(`/knowledge/${doc.id}`)
                                .then(setViewDocument)
                                .catch((error) => setNotice(error.message))
                            }
                          >
                            查看原文 <ArrowUpRight size={14} />
                          </button>
                        </div>
                        {doc.index_status === "failed" && (
                          <button
                            className="text-button"
                            onClick={async () => {
                              try {
                                await api(
                                  `/knowledge/${doc.id}/reindex`,
                                  "POST",
                                );
                                await refresh();
                              } catch (error) {
                                setNotice((error as Error).message);
                              }
                            }}
                          >
                            重新索引
                          </button>
                        )}
                      </section>
                    ))}
                  </div>
                </>
              )}
              {page === "assistant" && (
                <div className="assistant-layout">
                  <aside className="chat-sidebar">
                    <button
                      className="button new-chat"
                      onClick={() => startChat()}
                      disabled={busy}
                    >
                      <Plus size={16} />
                      新建对话
                    </button>
                    <span className="nav-caption">最近的分析</span>
                    <div className="session-list">
                      {sessions.map((session) => (
                        <button
                          key={session.id}
                          className={sessionId === session.id ? "selected" : ""}
                          onClick={() => void loadSession(session)}
                          disabled={busy}
                        >
                          <MessageSquare size={15} />
                          <div>
                            <strong>{session.title}</strong>
                            <small>
                              {session.device_id} · {time(session.created_at)}
                            </small>
                          </div>
                        </button>
                      ))}
                    </div>
                    <div className="chat-mode">
                      <span className="dot green" />
                      {health?.llm_mode === "ark"
                        ? "火山方舟模型"
                        : "规则演示模式"}
                      <p>
                        {health?.llm_mode === "ark"
                          ? "模型结果结合工具证据生成"
                          : "当前分析未调用大语言模型"}
                      </p>
                    </div>
                  </aside>
                  <section className="chat-panel">
                    <div className="chat-toolbar">
                      <span>
                        <span className="dot green" />
                        运维助手
                      </span>
                      <label>
                        分析设备
                        <select
                          aria-label="分析设备"
                          value={deviceId}
                          disabled={busy}
                          onChange={(event) => startChat(event.target.value)}
                        >
                          {devices.map((device) => (
                            <option key={device.id} value={device.id}>
                              {device.id} · {device.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="chat-scroll">
                      {messages.length === 0 ? (
                        <div className="chat-welcome">
                          <div className="chat-welcome-icon">
                            <Sparkles size={29} />
                          </div>
                          <h2>从一个问题，开始了解设备。</h2>
                          <p>
                            描述你关注的故障现象，助手将查询运行数据、
                            <br />
                            关联告警与日志，并检索相关运维知识。
                          </p>
                          <div className="suggestions">
                            {[
                              `分析 ${deviceId} 最近的温度与振动异常`,
                              `结合告警与日志，检查 ${deviceId} 的故障线索`,
                              `为 ${deviceId} 整理一份日常巡检建议`,
                            ].map((text) => (
                              <button
                                key={text}
                                onClick={() => void sendQuestion(text)}
                              >
                                <Activity size={17} />
                                <span>{text}</span>
                                <ArrowUpRight size={16} />
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : (
                        messages.map((message, i) => (
                          <div
                            className={`chat-message ${message.role}`}
                            key={i}
                          >
                            <div className={`message-avatar ${message.role}`}>
                              {message.role === "user" ? (
                                "运"
                              ) : (
                                <Sparkles size={17} />
                              )}
                            </div>
                            <div className="message-body">
                              <div className="message-label">
                                {message.role === "user" ? "你" : "运维助手"}
                                {message.role === "assistant" && (
                                  <span>
                                    {message.mode === "ark"
                                      ? "方舟模型分析"
                                      : "规则演示分析"}
                                  </span>
                                )}
                              </div>
                              <div className="message-content">
                                {message.role === "assistant" &&
                                message.mode === "ark" ? (
                                  <div className="report-markdown">
                                    <Markdown
                                      remarkPlugins={[remarkGfm]}
                                      skipHtml
                                      disallowedElements={["img"]}
                                    >
                                      {message.content}
                                    </Markdown>
                                  </div>
                                ) : (
                                  message.content
                                )}
                              </div>
                              {message.evidence?.length ? (
                                <details className="evidence-details">
                                  <summary>
                                    <BookOpen size={14} />
                                    查看分析证据 · {
                                      message.evidence.length
                                    }{" "}
                                    次工具查询
                                  </summary>
                                  {message.evidence.map((item, index) => (
                                    <div className="evidence-item" key={index}>
                                      <strong>
                                        {item.data.source || item.tool}
                                      </strong>
                                      {item.data.device && (
                                        <p>
                                          {item.data.device.id} · 温度{" "}
                                          {item.data.device.temperature}°C ·
                                          振动 {item.data.device.vibration}mm/s
                                        </p>
                                      )}
                                      {item.tool === "search_knowledge"
                                        ? item.data.records?.map((doc, j) => (
                                            <p key={j}>
                                              {doc.title} · 片段{" "}
                                              {doc.position + 1}
                                              <small>{doc.text}</small>
                                            </p>
                                          ))
                                        : item.data.records && (
                                            <p>
                                              查询到 {item.data.records.length}{" "}
                                              条记录
                                            </p>
                                          )}
                                    </div>
                                  ))}
                                </details>
                              ) : null}
                            </div>
                          </div>
                        ))
                      )}
                      {busy && (
                        <div className="analysis-progress">
                          <div>
                            <LoaderCircle size={16} className="spin" />
                            <strong>正在收集证据并分析</strong>
                          </div>
                          {steps.map((step, i) => (
                            <p key={i}>
                              <Check size={13} />
                              <span>{step.agent}</span>
                              {step.message}
                            </p>
                          ))}
                        </div>
                      )}
                      {streamText && (
                        <div className="stream-content">{streamText}</div>
                      )}
                      <div ref={chatEnd} />
                    </div>
                    <div className="composer-wrapper">
                      <div className="composer">
                        <textarea
                          placeholder={`描述你对 ${deviceId} 的问题，Enter 发送，Shift + Enter 换行`}
                          value={question}
                          disabled={busy}
                          onChange={(event) => setQuestion(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" && !event.shiftKey) {
                              event.preventDefault();
                              void sendQuestion();
                            }
                          }}
                          rows={2}
                        />
                        <div className="composer-bottom">
                          <span>
                            <Database size={13} />
                            设备数据 <span>·</span> <BookOpen size={13} />
                            运维知识
                          </span>
                          {busy ? (
                            <button
                              className="send-button"
                              aria-label="停止分析"
                              onClick={() => controller.current?.abort()}
                            >
                              <Square size={15} />
                            </button>
                          ) : (
                            <button
                              className="send-button"
                              aria-label="发送问题"
                              disabled={question.trim().length < 2}
                              onClick={() => void sendQuestion()}
                            >
                              <Send size={17} />
                            </button>
                          )}
                        </div>
                      </div>
                      <small className="composer-note">
                        分析结果用于辅助判断；请结合原始证据与现场检查确认原因。
                      </small>
                    </div>
                  </section>
                </div>
              )}
              {page !== "assistant" && (
                <footer className="page-footer">
                  <span>智维 · 工业智能运维系统</span>
                  <span>
                    {health?.demo_data ? "当前显示模拟设备数据" : "设备数据"}
                    <span className="footer-divider">/</span>
                    {health?.llm_mode === "ark"
                      ? "火山方舟模型"
                      : "规则演示分析"}
                  </span>
                </footer>
              )}
            </>
          )}
        </div>
      </main>
      {notice && (
        <div className="toast" role="status">
          <CircleHelp size={18} />
          <span>{notice}</span>
          <button aria-label="关闭提示" onClick={() => setNotice("")}>
            <X size={15} />
          </button>
        </div>
      )}
      {selectedDevice && (
        <Modal
          title={`${selectedDevice.name} · ${selectedDevice.id}`}
          onClose={() => setSelectedDevice(undefined)}
        >
          <div className="detail-heading">
            <Badge status={selectedDevice.status} />
            <span>
              {selectedDevice.area} ·{" "}
              {selectedDevice.kind === "pump" ? "水泵" : "电机"}
            </span>
          </div>
          <div className="detail-stats">
            {[
              ["温度", selectedDevice.temperature, "°C"],
              ["振动", selectedDevice.vibration, "mm/s"],
              ["电流", selectedDevice.current, "A"],
              ["压力", selectedDevice.pressure, "MPa"],
            ].map(([label, value, unit]) => (
              <div key={String(label)}>
                <small>{label}</small>
                <strong>
                  {value ?? "—"}
                  <span>{unit}</span>
                </strong>
              </div>
            ))}
          </div>
          <h3>最近 24 小时温度趋势</h3>
          <Chart
            values={history.map((row) => row.temperature)}
            labels={history.map((row) => shortHour(row.timestamp))}
          />
          <div className="modal-actions">
            <button
              className="button"
              onClick={async () => {
                try {
                  const result = await api<{ event_id: string }>(
                    `/devices/${selectedDevice.id}/simulate`,
                    "POST",
                  );
                  let completed = false;
                  for (let i = 0; i < 30; i++) {
                    const event = await api<{ status: string }>(
                      `/events/${result.event_id}`,
                    );
                    if (event.status === "completed") {
                      completed = true;
                      break;
                    }
                    if (event.status === "failed")
                      throw new Error("采样处理失败");
                    await new Promise((resolve) => setTimeout(resolve, 150));
                  }
                  if (!completed) throw new Error("采样仍在处理中，请稍后刷新");
                  const device = await api<Device>(
                    `/devices/${selectedDevice.id}`,
                  );
                  await showDevice(device);
                  await refresh();
                  setNotice("模拟采样已完成，数据已入库。");
                } catch (error) {
                  setNotice((error as Error).message);
                }
              }}
              disabled={!health?.simulation_enabled}
            >
              <RefreshCw size={15} />
              模拟一次采样
            </button>
            <button
              className="button primary"
              onClick={() => {
                startChat(selectedDevice.id);
                setSelectedDevice(undefined);
              }}
            >
              <Sparkles size={16} />
              分析此设备
            </button>
          </div>
        </Modal>
      )}
      {importOpen && (
        <Modal title="导入运维知识" onClose={() => setImportOpen(false)}>
          <label className="form-field">
            文档标题
            <input
              value={docTitle}
              onChange={(event) => setDocTitle(event.target.value)}
              placeholder="例如：循环水泵维修手册"
              maxLength={160}
            />
          </label>
          <label className="form-field">
            文档类型
            <select
              value={docCategory}
              onChange={(event) =>
                setDocCategory(event.target.value as Document["category"])
              }
            >
              {Object.entries(categories).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="file-input">
            <ArrowDownToLine size={17} />
            选择 .txt / .md 文件
            <input
              type="file"
              accept=".txt,.md"
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (file) {
                  if (file.size > 300_000) {
                    setNotice("请选择小于 300KB 的文本文件。");
                    return;
                  }
                  setDocContent(await file.text());
                  if (!docTitle) setDocTitle(file.name.replace(/\.[^.]+$/, ""));
                }
              }}
            />
          </label>
          <label className="form-field">
            文档内容
            <textarea
              rows={9}
              value={docContent}
              onChange={(event) => setDocContent(event.target.value)}
              placeholder="粘贴手册、案例或操作规程正文，至少 20 个字符…"
              maxLength={100_000}
            />
          </label>
          <div className="modal-actions">
            <small className="muted">导入后自动切片并建立知识索引</small>
            <button
              className="button primary"
              disabled={
                saving ||
                docTitle.trim().length < 2 ||
                docContent.trim().length < 20
              }
              onClick={() => void importDocument()}
            >
              {saving ? (
                <LoaderCircle className="spin" size={16} />
              ) : (
                <Plus size={16} />
              )}
              导入并建立索引
            </button>
          </div>
        </Modal>
      )}
      {registerOpen && (
        <Modal title="添加设备" onClose={() => setRegisterOpen(false)}>
          {(
            [
              ["id", "设备编号"],
              ["name", "设备名称"],
              ["area", "所属区域"],
            ] as const
          ).map(([key, label]) => (
            <label className="form-field" key={key}>
              {label}
              <input
                value={registration[key]}
                onChange={(event) =>
                  setRegistration((previous) => ({
                    ...previous,
                    [key]: event.target.value,
                  }))
                }
                placeholder={
                  key === "id"
                    ? "例如 P-109，仅字母、数字、下划线和短横线"
                    : label
                }
                maxLength={key === "id" ? 32 : 80}
              />
            </label>
          ))}
          <label className="form-field">
            设备类型
            <select
              value={registration.kind}
              onChange={(event) =>
                setRegistration((previous) => ({
                  ...previous,
                  kind: event.target.value as Device["kind"],
                }))
              }
            >
              <option value="pump">水泵</option>
              <option value="motor">电机</option>
            </select>
          </label>
          <div className="modal-actions">
            <small className="muted">登记后通过数据接入接口提交设备采样</small>
            <button
              className="button primary"
              disabled={
                saving ||
                !/^[A-Za-z0-9_-]{1,32}$/.test(registration.id) ||
                registration.name.trim().length < 2 ||
                registration.area.trim().length < 2
              }
              onClick={async () => {
                setSaving(true);
                try {
                  await api("/devices", "POST", registration);
                  setRegisterOpen(false);
                  setRegistration({ id: "", name: "", kind: "pump", area: "" });
                  await refresh();
                  setNotice("设备已登记，等待首条采样数据。");
                } catch (error) {
                  setNotice((error as Error).message);
                } finally {
                  setSaving(false);
                }
              }}
            >
              <Plus size={16} />
              登记设备
            </button>
          </div>
        </Modal>
      )}
      {viewDocument && (
        <Modal
          title={viewDocument.title}
          onClose={() => setViewDocument(undefined)}
        >
          <div className="detail-heading">
            <span className="document-category">
              {categories[viewDocument.category]}
            </span>
            <span>{viewDocument.chunks} 个知识片段</span>
          </div>
          <div className="document-content">{viewDocument.content}</div>
        </Modal>
      )}
    </div>
  );
}
