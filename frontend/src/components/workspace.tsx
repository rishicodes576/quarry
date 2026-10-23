"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock3,
  Database,
  ExternalLink,
  FileText,
  FlaskConical,
  Globe2,
  Layers3,
  Loader2,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Terminal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import AuthScreen from "./auth-screen";
import AccountSecurity from "./account-security";
import CapacityControls from "./capacity-controls";
import {
  api,
  ApiError,
  Conversation,
  Document,
  Evidence,
  Run,
  RunEvent,
  User,
} from "@/lib/client";

type View = "research" | "library" | "lab" | "evaluation" | "settings";
type Provider = {
  id: string;
  name: string;
  available: boolean;
  paid: boolean;
  description: string;
};
type Overview = {
  documents: number;
  chunks: number;
  completed_runs: number;
  pending_jobs: number;
  workspace: string;
  generation: string;
  demo: boolean;
};
type Hit = {
  title: string;
  text: string;
  score: number;
  page: number;
  section: string;
  document_id: string;
};
type SearchResult = {
  mode: string;
  hits: Hit[];
  latency_ms: number;
  candidate_count: number;
};
type Evaluation = {
  status: string;
  message?: string;
  results: {
    mode: string;
    recall_at_5: number;
    mrr: number;
    ndcg_at_5: number;
    precision_at_5: number;
    p50_ms: number;
    p95_ms: number;
    count: number;
  }[];
  manifest?: { case_count: number; test_count: number };
  created_at?: string;
  synthetic?: boolean;
};

const MODES = [
  { id: "dense", label: "Dense" },
  { id: "bm25", label: "BM25" },
  { id: "hybrid", label: "Hybrid" },
  { id: "hybrid_rerank", label: "Hybrid + rerank" },
];
const NAV = [
  { id: "research", label: "Research", icon: MessageSquare },
  { id: "library", label: "Source library", icon: BookOpen },
  { id: "lab", label: "Retrieval lab", icon: FlaskConical },
  { id: "evaluation", label: "Evaluations", icon: Activity },
] as const;
const TERMINAL_STATES = ["completed", "failed", "cancelled", "quota_exhausted"];
const SUGGESTIONS = [
  {
    tag: "SYSTEMS DESIGN",
    title: "How should we safely retry background jobs?",
    icon: Layers3,
  },
  {
    tag: "SECURITY",
    title: "How do we prevent prompt injection and SSRF?",
    icon: ShieldCheck,
  },
  {
    tag: "RETRIEVAL",
    title: "When does hybrid retrieval benefit from reranking?",
    icon: Search,
  },
];
const formatTime = (ms: number) =>
  ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`;

function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "small" : ""}`}>
      <span className="brand-mark">
        <Layers3 size={21} />
      </span>
      <span>
        quarry<span className="brand-dot">.</span>
      </span>
    </div>
  );
}

export default function Workspace({ demoEnabled }: { demoEnabled: boolean }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<View>("research");
  const [mobile, setMobile] = useState(false);
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [selected, setSelected] = useState<Evidence | null>(null);
  const [question, setQuestion] = useState("");
  const [provider, setProvider] = useState("extractive");
  const [mode, setMode] = useState("hybrid_rerank");
  const [allowWeb, setAllowWeb] = useState(false);
  const [paidConsent, setPaidConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [connection, setConnection] = useState("");
  const [importing, setImporting] = useState(false);
  const [url, setUrl] = useState("");
  const uploadRef = useRef<HTMLInputElement>(null);
  const active = !!run && !TERMINAL_STATES.includes(run.status);
  const canWrite = !!user && user.role !== "viewer";
  const modalOpen = importing || (view === "library" && !!selected);
  useEffect(() => {
    setSelected(null);
  }, [view]);
  useEffect(() => {
    if (!modalOpen) return;
    const prior = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    const controls = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),a[href],select:not(:disabled),[tabindex="0"]',
        ),
      ).filter((el) => el.offsetParent !== null);
    controls()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setImporting(false);
        setSelected(null);
      }
      if (event.key === "Tab") {
        const items = controls();
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    const focus = (event: FocusEvent) => {
      if (!dialog.contains(event.target as Node)) controls()[0]?.focus();
    };
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", key);
    document.addEventListener("focusin", focus);
    return () => {
      document.removeEventListener("keydown", key);
      document.removeEventListener("focusin", focus);
      document.body.style.overflow = overflow;
      prior?.focus();
    };
  }, [modalOpen]);

  const report = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) setUser(null);
    setError(
      e instanceof Error ? e.message : "Something went wrong. Please retry.",
    );
  }, []);

  const refresh = useCallback(async () => {
    const [o, d, c, p] = await Promise.all([
      api<Overview>("/overview"),
      api<Document[]>("/documents"),
      api<Conversation[]>("/conversations"),
      api<Provider[]>("/providers"),
    ]);
    setOverview(o);
    setDocuments(d);
    setConversations(c);
    setProviders(p);
  }, []);

  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (user) refresh().catch(report);
  }, [user, refresh, report]);
  useEffect(() => {
    if (
      !user ||
      !documents.some((d) => ["pending", "indexing"].includes(d.status))
    )
      return;
    const timer = setInterval(() => refresh().catch(report), 2500);
    return () => clearInterval(timer);
  }, [user, documents, refresh, report]);

  const loadRun = useCallback(async (id: string) => {
    const [r, e] = await Promise.all([
      api<Run>(`/runs/${id}`),
      api<RunEvent[]>(`/runs/${id}/events`),
    ]);
    setRun(r);
    setEvents(e);
    setSelected((previous) =>
      previous && r.evidence.some((x) => x.citation === previous.citation)
        ? r.evidence.find((x) => x.citation === previous.citation)!
        : r.evidence[0] || null,
    );
  }, []);

  useEffect(() => {
    if (!run || !active) return;
    const id = run.id;
    const source = new EventSource(`/api/v1/runs/${id}/stream`);
    source.onopen = () => setConnection("Live");
    source.addEventListener("update", () => {
      loadRun(id).catch(report);
    });
    source.addEventListener("done", () => {
      source.close();
      setConnection("");
      loadRun(id).catch(report);
      refresh().catch(report);
    });
    source.onerror = () => setConnection("Reconnecting · polling active");
    const timer = setInterval(() => loadRun(id).catch(report), 2500);
    return () => {
      source.close();
      clearInterval(timer);
      setConnection("");
    };
  }, [run?.id, active, loadRun, refresh, report]);

  async function signIn(email: string, password: string, code = "") {
    setBusy(true);
    setError("");
    try {
      setUser(
        await api<User>("/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password, code }),
        }),
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function submit(text = question, parent?: string) {
    if (!text.trim() || busy || active || !canWrite) return;
    setBusy(true);
    setError("");
    setView("research");
    try {
      let id = conversation;
      if (!id) {
        const c = await api<Conversation>("/conversations", {
          method: "POST",
          body: JSON.stringify({ title: "New research" }),
        });
        id = c.id;
        setConversation(id);
      }
      const result = await api<Run>("/runs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          conversation_id: id,
          question: text.trim(),
          provider,
          retrieval_mode: mode,
          allow_web: allowWeb,
          paid_consent: paidConsent,
          parent_run_id: parent || null,
        }),
      });
      setRun(result);
      setEvents([]);
      setSelected(null);
      setQuestion("");
      setPaidConsent(false);
      setRuns((previous) => [result, ...previous]);
      await refresh();
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }

  async function chooseConversation(id: string) {
    setConversation(id);
    setView("research");
    setMobile(false);
    setError("");
    try {
      const values = await api<Run[]>(`/runs?conversation_id=${id}`);
      setRuns(values);
      if (values[0]) await loadRun(values[0].id);
      else {
        setRun(null);
        setSelected(null);
        setEvents([]);
      }
    } catch (e) {
      report(e);
    }
  }

  async function upload(file: File) {
    if (file.size > 10 * 1024 * 1024) {
      setError("Choose a file smaller than 10 MiB.");
      return;
    }
    setUploading(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      await api("/documents", { method: "POST", body: form });
      await refresh();
    } catch (e) {
      report(e);
    } finally {
      setUploading(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  }

  async function importURL() {
    setUploading(true);
    setError("");
    try {
      await api("/documents/url", {
        method: "POST",
        body: JSON.stringify({ url }),
      });
      setUrl("");
      setImporting(false);
      await refresh();
    } catch (e) {
      report(e);
    } finally {
      setUploading(false);
    }
  }

  function newResearch() {
    setConversation(null);
    setRun(null);
    setRuns([]);
    setEvents([]);
    setSelected(null);
    setQuestion("");
    setView("research");
    setMobile(false);
  }
  const changeView = (id: View) => {
    setView(id);
    setMobile(false);
    setError("");
  };

  if (loading)
    return (
      <div className="boot">
        <Brand />
        <Loader2 className="spin" />
        <span>Opening your workspace…</span>
      </div>
    );
  if (!user)
    return (
      <AuthScreen
        demoEnabled={demoEnabled}
        busy={busy}
        error={error}
        signIn={signIn}
      />
    );

  return (
    <div className="shell">
      <a href="#main" className="skip-link">
        Skip to workspace
      </a>
      <input
        ref={uploadRef}
        type="file"
        accept=".pdf,.md,.txt,.html"
        className="sr-only"
        aria-label="Upload document"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload(f);
        }}
      />
      <aside className={`sidebar ${mobile ? "open" : ""}`}>
        <Brand />
        <button
          className="workspace-switch"
          onClick={() => changeView("settings")}
        >
          <span className="workspace-icon">
            <Layers3 size={16} />
          </span>
          <span>
            {overview?.workspace || "Workspace"}
            <small>Personal workspace</small>
          </span>
          <ChevronDown size={14} />
        </button>
        <button className="new-research" onClick={newResearch}>
          <Plus size={16} /> New research <kbd>N</kbd>
        </button>
        <nav aria-label="Main navigation">
          {NAV.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? "selected" : ""}`}
              onClick={() => changeView(item.id)}
            >
              <item.icon size={18} />
              {item.label}
              {item.id === "library" && (
                <span className="nav-count">
                  {documents.filter((d) => d.status === "ready").length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="recent-heading">
          RECENT RESEARCH <span>{conversations.length}</span>
        </div>
        <div className="recent-list">
          {conversations.length === 0 ? (
            <p className="muted small-text">Your research will appear here.</p>
          ) : (
            conversations.slice(0, 8).map((c) => (
              <button
                title={c.title}
                key={c.id}
                className={`recent-item ${conversation === c.id ? "current" : ""}`}
                onClick={() => chooseConversation(c.id)}
              >
                <MessageSquare size={14} />
                <span>{c.title}</span>
              </button>
            ))
          )}
        </div>
        <div className="sidebar-bottom">
          <div className="local-note">
            <span className="status-dot" />
            <div>
              Runs on your machine
              <small>Local search · explicit providers</small>
            </div>
            <ShieldCheck size={15} />
          </div>
          <button
            className={`nav-item ${view === "settings" ? "selected" : ""}`}
            onClick={() => changeView("settings")}
          >
            <Settings2 size={18} /> Settings
          </button>
          <div className="account">
            <span className="avatar">
              {user.email === "demo@quarry.local" ? "DL" : "RC"}
            </span>
            <div>
              <strong>{user.email.split("@")[0]}</strong>
              <small>{user.role} access</small>
            </div>
            <button
              className="icon-button"
              title="Sign out"
              onClick={async () => {
                try {
                  await api("/auth/logout", { method: "POST" });
                  setUser(null);
                } catch (e) {
                  report(e);
                }
              }}
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={20} />
            </button>
            <Layers3 size={15} />
            <span>{overview?.workspace || "Workspace"}</span>
            <ChevronRight size={13} />
            <strong>
              {view === "library"
                ? "Source library"
                : view === "lab"
                  ? "Retrieval lab"
                  : view === "evaluation"
                    ? "Evaluations"
                    : view === "settings"
                      ? "Settings"
                      : "Research"}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="version">v0.1</span>
            <span className="local-badge">
              <span className="status-dot" /> Local workspace
            </span>
          </div>
        </header>
        <main id="main">
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {view === "research" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <span className="tiny-square" /> YOUR EVIDENCE WORKSPACE
                  </div>
                  <h1>
                    Research, with receipts<span>.</span>
                  </h1>
                  <p>
                    Ask better questions. Follow the evidence. Make the call.
                  </p>
                </div>
                <button
                  className="button secondary"
                  disabled={!canWrite || uploading}
                  onClick={() => uploadRef.current?.click()}
                >
                  {uploading ? (
                    <Loader2 className="spin" size={16} />
                  ) : (
                    <Upload size={16} />
                  )}{" "}
                  Add sources
                </button>
              </div>
              <div className="stats-row">
                <Stat
                  icon={FileText}
                  label="Indexed sources"
                  value={overview?.documents || 0}
                />
                <Stat
                  icon={Layers3}
                  label="Searchable passages"
                  value={overview?.chunks || 0}
                />
                <Stat
                  icon={CheckCircle2}
                  label="Completed research"
                  value={overview?.completed_runs || 0}
                />
                <Stat
                  icon={ShieldCheck}
                  label="Provider switching"
                  value="Explicit only"
                />
              </div>
              <div className="research-grid">
                <section
                  className="research-main"
                  aria-label="Research conversation"
                >
                  <div className="section-bar">
                    <span>
                      <MessageSquare size={16} />{" "}
                      {run ? "Research brief" : "Research desk"}
                    </span>
                    <span className="subtle-label">
                      {run
                        ? run.id.slice(0, 8)
                        : "A question is a good place to start"}
                    </span>
                  </div>
                  {run ? (
                    <div className="run-content">
                      <div className="run-question">
                        <span className="question-marker">Q</span>
                        <h2>{run.question}</h2>
                      </div>
                      <div className="run-meta">
                        <span className={`status-pill ${run.status}`}>
                          <span className="status-dot" />
                          {run.status.replaceAll("_", " ")}
                        </span>
                        <span>
                          {run.provider === "extractive"
                            ? "Local evidence"
                            : run.provider === "groq"
                              ? "Groq · Free Plan"
                              : "Paid provider · consent recorded"}
                        </span>
                        <span>
                          {
                            MODES.find((m) => m.id === run.retrieval_mode)
                              ?.label
                          }
                        </span>
                        {connection && (
                          <span className="live-label">{connection}</span>
                        )}
                      </div>
                      {events.length > 0 && (
                        <div
                          className="timeline"
                          aria-label="Execution timeline"
                        >
                          {events
                            .filter((e) =>
                              [
                                "stage_completed",
                                "tool",
                                "retrying",
                                "failed",
                              ].includes(e.kind),
                            )
                            .map((e) => (
                              <div
                                className={`timeline-item ${e.kind === "failed" ? "failed" : ""}`}
                                key={e.id}
                              >
                                {e.kind === "failed" ? (
                                  <X size={13} />
                                ) : (
                                  <Check size={13} />
                                )}
                                <span>
                                  {String(
                                    e.payload.stage || e.payload.name || e.kind,
                                  ).replaceAll("_", " ")}
                                </span>
                                {typeof e.payload.latency_ms === "number" && (
                                  <small>
                                    {formatTime(e.payload.latency_ms)}
                                  </small>
                                )}
                              </div>
                            ))}
                          {active && (
                            <div className="timeline-item working">
                              <Loader2 size={13} className="spin" /> Working
                              through the evidence
                            </div>
                          )}
                        </div>
                      )}
                      {run.status === "quota_exhausted" && (
                        <div className="notice warning">
                          <Clock3 size={20} />
                          <div>
                            <strong>
                              Quota reached. Your evidence is saved.
                            </strong>
                            <p>{run.error}</p>
                            <p>
                              Select an available provider below and retry. Paid
                              providers require explicit consent.
                            </p>
                            <button
                              className="button secondary"
                              disabled={busy}
                              onClick={() => submit(run.question, run.id)}
                            >
                              Create explicit continuation{" "}
                              <ArrowRight size={14} />
                            </button>
                          </div>
                        </div>
                      )}
                      {["failed", "cancelled"].includes(run.status) && (
                        <div className="notice warning">
                          <Activity size={18} />
                          <div>
                            <strong>
                              {run.status === "cancelled"
                                ? "Research cancelled"
                                : "Research needs attention"}
                            </strong>
                            <p>
                              {run.error ||
                                "Stored evidence and execution events remain available."}
                            </p>
                            <button
                              className="text-button"
                              onClick={() => submit(run.question, run.id)}
                            >
                              Retry as a linked run <ArrowRight size={14} />
                            </button>
                          </div>
                        </div>
                      )}
                      {run.answer && (
                        <article
                          className="answer"
                          aria-label="Research answer"
                        >
                          <Answer
                            text={run.answer}
                            select={(citation) =>
                              setSelected(
                                run.evidence.find(
                                  (e) => e.citation === citation,
                                ) || null,
                              )
                            }
                          />
                        </article>
                      )}
                      {run.status === "completed" && (
                        <div className="answer-footer">
                          <span>
                            <CheckCircle2 size={14} /> {run.evidence.length}{" "}
                            cited passages <span className="separator">·</span>{" "}
                            {typeof run.diagnostics.total_ms === "number"
                              ? formatTime(run.diagnostics.total_ms)
                              : "Timing unavailable"}
                          </span>
                          <a
                            className="text-button"
                            href={`/api/v1/runs/${run.id}/export`}
                          >
                            <ArrowDownToLine size={14} /> Export brief
                          </a>
                        </div>
                      )}
                      {runs.length > 1 && (
                        <div className="previous-runs">
                          <label htmlFor="previous-runs">
                            Conversation history
                          </label>
                          <select
                            id="previous-runs"
                            value={run.id}
                            onChange={(e) =>
                              loadRun(e.target.value).catch(report)
                            }
                          >
                            {runs.map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.question.slice(0, 70)} · {r.status}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="research-welcome">
                      <div className="welcome-art">
                        <div className="orbit orbit-one" />
                        <div className="orbit orbit-two" />
                        <div className="welcome-symbol">
                          <Layers3 size={31} strokeWidth={1.4} />
                        </div>
                        <span className="orbit-point point-one" />
                        <span className="orbit-point point-two" />
                      </div>
                      <span className="pill muted-pill">THINK IT THROUGH</span>
                      <h2>
                        What are you building
                        <br />a case for?
                      </h2>
                      <p>
                        Bring your documents and a question.
                        <br />
                        Quarry connects the passages and keeps the trail.
                      </p>
                      <div className="suggestion-list">
                        {SUGGESTIONS.map((s) => (
                          <button
                            key={s.tag}
                            onClick={() => setQuestion(s.title)}
                          >
                            <s.icon size={18} />
                            <span>
                              <small>{s.tag}</small>
                              {s.title}
                            </span>
                            <ArrowRight size={16} />
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  <form
                    className="composer"
                    onSubmit={(e) => {
                      e.preventDefault();
                      submit();
                    }}
                  >
                    <label htmlFor="question" className="sr-only">
                      Research question
                    </label>
                    <textarea
                      id="question"
                      placeholder="Ask a question worth investigating…"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      maxLength={2000}
                      disabled={!canWrite}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                          e.preventDefault();
                          submit();
                        }
                      }}
                    />
                    <div className="composer-tools">
                      <div>
                        <label className="select-label">
                          <Sparkles size={14} />
                          <select
                            aria-label="Generation provider"
                            value={provider}
                            onChange={(e) => {
                              setProvider(e.target.value);
                              setPaidConsent(false);
                            }}
                          >
                            {providers.map((p) => (
                              <option
                                key={p.id}
                                value={p.id}
                                disabled={!p.available}
                              >
                                {p.name}
                                {!p.available ? " · not configured" : ""}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          type="button"
                          className={`toggle-chip ${allowWeb ? "enabled" : ""}`}
                          aria-pressed={allowWeb}
                          onClick={() => setAllowWeb(!allowWeb)}
                        >
                          <Globe2 size={14} /> Web
                        </button>
                      </div>
                      {active ? (
                        <button
                          type="button"
                          className="send-button stop-button"
                          aria-label="Cancel research"
                          onClick={() =>
                            api(`/runs/${run.id}/cancel`, {
                              method: "POST",
                            }).catch(report)
                          }
                        >
                          <Square size={15} />
                        </button>
                      ) : (
                        <button
                          type="submit"
                          className="send-button"
                          aria-label="Start research"
                          disabled={
                            !question.trim() ||
                            busy ||
                            !canWrite ||
                            (provider === "openai" && !paidConsent)
                          }
                        >
                          {busy ? (
                            <Loader2 size={17} className="spin" />
                          ) : (
                            <ArrowUp size={18} />
                          )}
                        </button>
                      )}
                    </div>
                    {provider === "openai" && (
                      <label className="consent">
                        <input
                          type="checkbox"
                          checked={paidConsent}
                          onChange={(e) => setPaidConsent(e.target.checked)}
                        />{" "}
                        I explicitly authorize paid generation for this run.
                      </label>
                    )}
                  </form>
                  <div className="composer-note">
                    <ShieldCheck size={12} />{" "}
                    {provider === "extractive"
                      ? "Local retrieval. Extractive answers. No generation API calls."
                      : "Your selected provider only. No automatic fallback."}
                    <span>Ctrl ↵ to research</span>
                  </div>
                </section>
                <aside
                  className="evidence-panel"
                  aria-label="Evidence inspector"
                >
                  <div className="section-bar">
                    <span>
                      <BookOpen size={16} /> Evidence
                    </span>
                    <span className="count-badge">
                      {run?.evidence.length || 0}
                    </span>
                  </div>
                  {selected ? (
                    <EvidencePanel
                      evidence={selected}
                      all={run?.evidence || []}
                      select={setSelected}
                    />
                  ) : (
                    <div className="evidence-empty">
                      <div className="source-placeholder">
                        <FileText size={25} />
                        <div />
                        <div />
                        <div />
                      </div>
                      <h3>Every claim has a trail.</h3>
                      <p>
                        Supporting passages appear here as your research runs.
                        Select a citation to inspect its source.
                      </p>
                      <div className="divider" />
                      <div className="small-heading">
                        IN YOUR LIBRARY <span>{overview?.documents || 0}</span>
                      </div>
                      {documents.slice(0, 4).map((d) => (
                        <button
                          className="mini-document"
                          key={d.id}
                          onClick={() => changeView("library")}
                        >
                          <span className="file-icon">
                            <FileText size={15} />
                          </span>
                          <div>
                            <strong>{d.title}</strong>
                            <small>
                              {d.status === "ready"
                                ? `${d.chunk_count} passages`
                                : d.status}
                            </small>
                          </div>
                        </button>
                      ))}
                      <button
                        className="text-button library-link"
                        onClick={() => changeView("library")}
                      >
                        Explore source library <ArrowRight size={14} />
                      </button>
                    </div>
                  )}
                  <div className="evidence-bottom">
                    <ShieldCheck size={14} />
                    <span>
                      Source references are inspectable.
                      <br />
                      Factual support needs evaluation.
                    </span>
                  </div>
                </aside>
              </div>
            </>
          )}
          {view === "library" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <BookOpen size={13} /> KNOWLEDGE, ORGANIZED
                  </div>
                  <h1>
                    Source library<span>.</span>
                  </h1>
                  <p>
                    Your documents, their provenance, and every indexed passage.
                  </p>
                </div>
                <div className="button-row">
                  <button
                    className="button secondary"
                    disabled={!canWrite}
                    onClick={() => setImporting(true)}
                  >
                    <Globe2 size={16} /> Import URL
                  </button>
                  <button
                    className="button primary"
                    disabled={!canWrite || uploading}
                    onClick={() => uploadRef.current?.click()}
                  >
                    {uploading ? (
                      <Loader2 size={16} className="spin" />
                    ) : (
                      <Plus size={16} />
                    )}{" "}
                    Add document
                  </button>
                </div>
              </div>
              <div className="notice">
                <ShieldCheck size={20} />
                <div>
                  <strong>Original sample engineering notes included</strong>
                  <p>
                    Sample content is synthetic and labeled. Upload real
                    documents to research your own engineering decisions. PDF,
                    Markdown, text, and HTML · up to 10 MiB.
                  </p>
                </div>
              </div>
              <div className="library-grid">
                {documents.map((d) => (
                  <DocumentCard
                    key={d.id}
                    document={d}
                    canWrite={canWrite}
                    inspect={async () => {
                      try {
                        const passages = await api<
                          {
                            id: string;
                            text: string;
                            page: number;
                            section: string;
                          }[]
                        >(`/documents/${d.id}/passages`);
                        setSelected({
                          citation: "E1",
                          title: d.title,
                          text: passages.map((p) => p.text).join("\n\n"),
                          kind: "document",
                          document_id: d.id,
                          page: 1,
                          section: "Source preview",
                          source_url: d.source_url,
                          content_hash: d.content_hash,
                          score: 0,
                          retrieved_at: d.created_at,
                        });
                      } catch (e) {
                        report(e);
                      }
                    }}
                    remove={async () => {
                      if (!confirm(`Remove “${d.title}” from retrieval?`))
                        return;
                      try {
                        await api(`/documents/${d.id}`, { method: "DELETE" });
                        await refresh();
                      } catch (e) {
                        report(e);
                      }
                    }}
                    retry={async () => {
                      try {
                        await api(`/documents/${d.id}/retry`, {
                          method: "POST",
                        });
                        await refresh();
                      } catch (e) {
                        report(e);
                      }
                    }}
                  />
                ))}
                {documents.length === 0 && (
                  <div className="empty-state">
                    <Upload size={35} />
                    <h2>Your evidence starts here</h2>
                    <p>
                      Add a technical document to build your knowledge base.
                    </p>
                  </div>
                )}
              </div>
              {selected && (
                <div
                  className="modal-backdrop"
                  onClick={() => setSelected(null)}
                >
                  <section
                    className="modal source-modal"
                    role="dialog"
                    aria-modal="true"
                    aria-labelledby="source-title"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="modal-heading">
                      <h2 id="source-title">{selected.title}</h2>
                      <button
                        className="icon-button"
                        aria-label="Close source preview"
                        onClick={() => setSelected(null)}
                      >
                        <X size={19} />
                      </button>
                    </div>
                    <p className="source-text">
                      {selected.text ||
                        "Passages will be available when indexing completes."}
                    </p>
                    <a
                      className="button secondary"
                      href={`/api/v1/documents/${selected.document_id}/source`}
                    >
                      <ArrowDownToLine size={15} /> Download original
                    </a>
                  </section>
                </div>
              )}
            </>
          )}
          {view === "lab" && (
            <RetrievalLab report={report} mode={mode} setMode={setMode} />
          )}
          {view === "evaluation" && <Evaluations report={report} />}
          {view === "settings" && (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">
                    <Settings2 size={13} /> WORKSPACE CONTROLS
                  </div>
                  <h1>
                    Make the rules explicit<span>.</span>
                  </h1>
                  <p>
                    Provider choices, access, and the environment behind your
                    research.
                  </p>
                </div>
              </div>
              <div className="settings-grid">
                <section className="panel settings-panel">
                  <h2>Generation providers</h2>
                  <p className="muted">
                    A run uses the provider you select. Quota exhaustion
                    preserves progress and stops execution.
                  </p>
                  {providers.map((p) => (
                    <div className="provider-card" key={p.id}>
                      <div className="provider-symbol">
                        {p.id === "extractive" ? (
                          <Database size={20} />
                        ) : (
                          <Sparkles size={20} />
                        )}
                      </div>
                      <div>
                        <strong>{p.name}</strong>
                        <p>{p.description}</p>
                      </div>
                      <span
                        className={`status-pill ${p.available ? "ready" : "disabled"}`}
                      >
                        {p.available ? "Available" : "Disabled"}
                      </span>
                    </div>
                  ))}
                  <div className="code-note">
                    <Terminal size={16} />
                    <div>
                      <strong>Configure a free key locally</strong>
                      <code>python scripts/manage.py configure-groq</code>
                      <p>
                        Use a Groq Free Plan organization with no billing
                        enabled. Secrets stay server-side.
                      </p>
                    </div>
                  </div>
                </section>
                <section className="panel settings-panel">
                  <h2>Execution boundaries</h2>
                  <dl className="settings-list">
                    <div>
                      <dt>Runtime</dt>
                      <dd>Docker Compose</dd>
                    </div>
                    <div>
                      <dt>Persistence</dt>
                      <dd>PostgreSQL + private S3</dd>
                    </div>
                    <div>
                      <dt>Retrieval</dt>
                      <dd>Qdrant · local ONNX</dd>
                    </div>
                    <div>
                      <dt>Default workspace concurrency</dt>
                      <dd>4 jobs</dd>
                    </div>
                    <div>
                      <dt>Daily model budget</dt>
                      <dd>30,000 tokens</dd>
                    </div>
                    <div>
                      <dt>Maximum tool calls</dt>
                      <dd>6 per run</dd>
                    </div>
                    <div>
                      <dt>Your permission</dt>
                      <dd>{user.role}</dd>
                    </div>
                  </dl>
                  <div className="notice">
                    <ShieldCheck size={18} />
                    <p>
                      Shared quotas, leased workers, explicit provider consent,
                      and durable execution events are enforced by the backend.
                    </p>
                  </div>
                </section>
              </div>
              <AccountSecurity user={user} signOut={() => setUser(null)} />
              <CapacityControls user={user} />
            </>
          )}
          <footer className="page-footer">
            <span>
              <Layers3 size={12} /> Grounded in evidence. Open to inspection.
            </span>
            <span>Quarry / Engineering research workspace</span>
          </footer>
        </main>
      </div>
      {importing && (
        <div className="modal-backdrop">
          <form
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="import-title"
            onSubmit={(e) => {
              e.preventDefault();
              importURL();
            }}
          >
            <div className="modal-heading">
              <h2 id="import-title">Import a public source</h2>
              <button
                className="icon-button"
                type="button"
                aria-label="Close import dialog"
                onClick={() => setImporting(false)}
              >
                <X size={18} />
              </button>
            </div>
            <p>
              Quarry fetches public HTTP(S) pages and preserves a source
              snapshot. Private addresses and redirects to internal services are
              rejected.
            </p>
            <label htmlFor="source-url">Source URL</label>
            <input
              id="source-url"
              type="url"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://docs.example.com/design"
            />
            <button className="button primary" disabled={uploading}>
              {uploading ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Globe2 size={16} />
              )}{" "}
              Import source
            </button>
          </form>
        </div>
      )}
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof FileText;
  label: string;
  value: number | string;
}) {
  return (
    <div className="stat">
      <div>
        <Icon size={16} />
        <span>{label}</span>
      </div>
      <strong>{value}</strong>
    </div>
  );
}

function Answer({
  text,
  select,
}: {
  text: string;
  select: (citation: string) => void;
}) {
  return (
    <>
      {text.split(/\n\n+/).map((paragraph, i) => {
        if (paragraph.startsWith("## "))
          return <h3 key={i}>{paragraph.slice(3)}</h3>;
        const pieces = paragraph.split(/(\[E\d+\])/g);
        return (
          <p key={i}>
            {pieces.map((piece, j) =>
              /^\[E\d+\]$/.test(piece) ? (
                <button
                  className="citation"
                  key={j}
                  onClick={() => select(piece.slice(1, -1))}
                >
                  {piece.slice(1, -1)}
                  <ExternalLink size={10} />
                </button>
              ) : (
                <span key={j}>{piece}</span>
              ),
            )}
          </p>
        );
      })}
    </>
  );
}

function EvidencePanel({
  evidence,
  all,
  select,
}: {
  evidence: Evidence;
  all: Evidence[];
  select: (e: Evidence) => void;
}) {
  return (
    <div className="evidence-detail">
      <div className="evidence-tabs">
        {all.map((e) => (
          <button
            key={e.citation}
            className={e.citation === evidence.citation ? "active" : ""}
            onClick={() => select(e)}
          >
            {e.citation}
          </button>
        ))}
      </div>
      <div className="source-kind">
        <FileText size={13} />
        {evidence.kind.replaceAll("_", " ")}
      </div>
      <h3>{evidence.title}</h3>
      <div className="source-location">
        Page {evidence.page} <span>·</span> {evidence.section}
      </div>
      <blockquote>{evidence.text}</blockquote>
      <dl className="source-provenance">
        <div>
          <dt>Retrieved</dt>
          <dd>
            {evidence.retrieved_at
              ? new Date(evidence.retrieved_at * 1000).toLocaleString()
              : "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Content fingerprint</dt>
          <dd className="hash" title={evidence.content_hash}>
            {evidence.content_hash?.slice(0, 20) || "Unavailable"}…
          </dd>
        </div>
      </dl>
      {evidence.source_url && /^https?:\/\//.test(evidence.source_url) && (
        <a
          href={evidence.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="button secondary"
        >
          Visit public source <ExternalLink size={13} />
        </a>
      )}
      {evidence.document_id && (
        <a
          className="text-button"
          href={`/api/v1/documents/${evidence.document_id}/source`}
        >
          <ArrowDownToLine size={14} /> Download original
        </a>
      )}
    </div>
  );
}

function DocumentCard({
  document: d,
  canWrite,
  inspect,
  remove,
  retry,
}: {
  document: Document;
  canWrite: boolean;
  inspect: () => void;
  remove: () => void;
  retry: () => void;
}) {
  return (
    <div className="document-card">
      <div className="document-card-top">
        <span className="file-icon">
          <FileText size={22} />
        </span>
        <span className={`status-pill ${d.status}`}>
          {["indexing", "pending"].includes(d.status) && (
            <Loader2 size={11} className="spin" />
          )}
          {d.status}
        </span>
      </div>
      <button className="document-title" onClick={inspect}>
        {d.title}
      </button>
      <p>
        {d.chunk_count} passages <span>·</span> Revision {d.version}
      </p>
      {d.error && <p className="document-error">{d.error}</p>}
      <div className="document-card-bottom">
        <code>{d.content_hash.slice(0, 12)}</code>
        <div>
          {d.status === "failed" && canWrite && (
            <button className="text-button" onClick={retry}>
              Retry
            </button>
          )}
          <button
            className="icon-button"
            aria-label={`Inspect ${d.title}`}
            onClick={inspect}
          >
            <Search size={15} />
          </button>
          {canWrite && (
            <button
              className="icon-button"
              aria-label={`Delete ${d.title}`}
              onClick={remove}
            >
              <Trash2 size={15} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function RetrievalLab({
  report,
  mode,
  setMode,
}: {
  report: (e: unknown) => void;
  mode: string;
  setMode: (mode: string) => void;
}) {
  const [query, setQuery] = useState(
    "How can a client safely retry a research submission?",
  );
  const [results, setResults] = useState<SearchResult[]>([]);
  const [busy, setBusy] = useState(false);
  async function compare() {
    setBusy(true);
    try {
      setResults(
        await api<SearchResult[]>("/search/compare", {
          method: "POST",
          body: JSON.stringify({ query, modes: MODES.map((m) => m.id) }),
        }),
      );
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <FlaskConical size={13} /> INSPECT THE RETRIEVAL
          </div>
          <h1>
            Four paths to the evidence<span>.</span>
          </h1>
          <p>
            One query, the same corpus. Compare ranking, context, and measured
            latency.
          </p>
        </div>
      </div>
      <form
        className="lab-query"
        onSubmit={(e) => {
          e.preventDefault();
          compare();
        }}
      >
        <Search size={19} />
        <label htmlFor="lab-query" className="sr-only">
          Comparison query
        </label>
        <input
          id="lab-query"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          required
          minLength={2}
          maxLength={2000}
        />
        <button className="button primary" disabled={busy}>
          {busy ? (
            <Loader2 size={16} className="spin" />
          ) : (
            <FlaskConical size={16} />
          )}{" "}
          Compare retrieval
        </button>
      </form>
      <div className="lab-grid">
        {MODES.map((m) => {
          const r = results.find((r) => r.mode === m.id);
          return (
            <section className="panel lab-card" key={m.id}>
              <div className="lab-card-heading">
                <h2>{m.label}</h2>
                <span className="method-number">0{MODES.indexOf(m) + 1}</span>
              </div>
              <p className="method-description">
                {m.id === "dense"
                  ? "Semantic similarity across local embeddings."
                  : m.id === "bm25"
                    ? "Sparse lexical matching with corpus IDF."
                    : m.id === "hybrid"
                      ? "Dense + sparse, fused by reciprocal rank."
                      : "Hybrid candidates reordered by a cross-encoder."}
              </p>
              {r ? (
                <>
                  <div className="lab-timing">
                    <strong>{formatTime(r.latency_ms)}</strong>
                    <span>{r.candidate_count} candidates</span>
                  </div>
                  <div className="lab-hits">
                    {r.hits.slice(0, 5).map((h, i) => (
                      <div className="lab-hit" key={i}>
                        <div>
                          <span>#{i + 1}</span>
                          <code>{h.score.toFixed(3)}</code>
                        </div>
                        <h3>{h.title}</h3>
                        <p>{h.text.slice(0, 220)}…</p>
                      </div>
                    ))}
                    {r.hits.length === 0 && (
                      <p className="muted">No eligible documents found.</p>
                    )}
                  </div>
                </>
              ) : (
                <div className="lab-placeholder">
                  <Layers3 size={25} />
                  <span>Run a comparison to inspect results</span>
                </div>
              )}
              <button
                className={`button ${mode === m.id ? "primary" : "secondary"}`}
                onClick={() => setMode(m.id)}
              >
                {mode === m.id ? (
                  <>
                    <Check size={14} /> Selected for research
                  </>
                ) : (
                  "Use for research"
                )}
              </button>
            </section>
          );
        })}
      </div>
      <div className="notice">
        <Activity size={19} />
        <p>
          Latency is measured for this request, including local encoding and
          search. Cross-encoder scores are ranking signals, not
          factual-confidence percentages. Use the frozen benchmark for aggregate
          comparisons.
        </p>
      </div>
    </>
  );
}

function Evaluations({ report }: { report: (e: unknown) => void }) {
  const [data, setData] = useState<Evaluation | null>(null);
  const [copied, setCopied] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setLoadError(false);
    api<Evaluation>("/evaluations", { signal: controller.signal })
      .then(setData)
      .catch((e) => {
        if (!controller.signal.aborted) {
          setLoadError(true);
          if (e instanceof ApiError && e.status === 401) report(e);
        }
      });
    return () => controller.abort();
  }, [report, attempt]);
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <Activity size={13} /> MEASURE WHAT MATTERS
          </div>
          <h1>
            Evidence for the engine<span>.</span>
          </h1>
          <p>Frozen cases, reproducible runs, and results you can audit.</p>
        </div>
        <button
          className="button secondary"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(
                "python scripts/manage.py benchmark",
              );
              setCopied(true);
            } catch {
              report(new Error("Run: python scripts/manage.py benchmark"));
            }
          }}
        >
          <Terminal size={15} />
          {copied ? "Command copied" : "Copy benchmark command"}
        </button>
      </div>
      <div className="stats-row">
        <Stat icon={FileText} label="Versioned cases" value={120} />
        <Stat icon={FlaskConical} label="Retrieval strategies" value={4} />
        <Stat icon={ShieldCheck} label="Frozen test cases" value={90} />
        <Stat
          icon={Database}
          label="Generation API spend"
          value="$0 required"
        />
      </div>
      {!data && !loadError ? (
        <section className="panel evaluation-empty" role="status">
          <Loader2 className="spin" size={28} />
          <h2>Loading measured results.</h2>
          <p>Checking the saved benchmark artifact.</p>
        </section>
      ) : loadError ? (
        <section className="panel evaluation-empty" role="alert">
          <h2>Results could not be loaded.</h2>
          <p>Your saved artifacts remain on the server.</p>
          <button
            className="button secondary"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Try again
          </button>
        </section>
      ) : data && (data.status === "completed" || data.status === "partial") ? (
        <section className="panel evaluation-panel">
          <div className="section-bar">
            <span>
              <CheckCircle2 size={16} />{" "}
              {data.status === "partial"
                ? "Partial retrieval results — inspect failed cases"
                : "Measured retrieval results"}
            </span>
            <span className="subtle-label">{data.created_at}</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Strategy</th>
                  <th>Recall@5</th>
                  <th>MRR</th>
                  <th>nDCG@5</th>
                  <th>Precision@5</th>
                  <th>P50</th>
                  <th>P95</th>
                  <th>Cases</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r) => (
                  <tr key={r.mode}>
                    <td>{MODES.find((m) => m.id === r.mode)?.label}</td>
                    <td>{r.recall_at_5.toFixed(3)}</td>
                    <td>{r.mrr.toFixed(3)}</td>
                    <td>{r.ndcg_at_5.toFixed(3)}</td>
                    <td>{r.precision_at_5.toFixed(3)}</td>
                    <td>{formatTime(r.p50_ms)}</td>
                    <td>{formatTime(r.p95_ms)}</td>
                    <td>{r.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="evaluation-footnote">
            Authored synthetic engineering corpus. Source-level labels. Results
            describe this dataset and configuration; model-judged metrics and
            live-provider tests are reported separately in the audit artifacts.
          </div>
        </section>
      ) : (
        <div className="panel evaluation-empty">
          <div className="empty-icon">
            <FlaskConical size={32} />
          </div>
          <span className="pill muted-pill">READY TO MEASURE</span>
          <h2>Run the frozen evaluation set.</h2>
          <p>
            Benchmark all four strategies against versioned relevance labels.
            <br />
            Measured results appear here after the command completes.
          </p>
          <code>python scripts/manage.py benchmark</code>
          <span className="muted small-text">
            Uses local models and services. No generation key required.
          </span>
        </div>
      )}
      <div className="evaluation-notes">
        <section className="panel">
          <h3>
            <Search size={17} /> Retrieval quality
          </h3>
          <p>
            Recall, reciprocal rank, and discounted gain measure evidence
            discovery and ordering.
          </p>
        </section>
        <section className="panel">
          <h3>
            <Clock3 size={17} /> Honest performance
          </h3>
          <p>
            Raw case timings, model hashes, warm/cold conditions, and failures
            accompany aggregate results.
          </p>
        </section>
        <section className="panel">
          <h3>
            <BookOpen size={17} /> Answer support
          </h3>
          <p>
            Ragas and manual-review artifacts assess generated answers
            separately from reference validity.
          </p>
        </section>
      </div>
    </>
  );
}
