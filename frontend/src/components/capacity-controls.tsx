"use client";
import { useEffect, useState } from "react";
import { api, User } from "@/lib/client";
type Usage = {
  plan: string;
  weight: number;
  tokens: { used: number; reserved: number; daily_limit: number };
  shared_tokens: { used: number; reserved: number; daily_limit: number };
  storage: { bytes: number; limit_bytes: number };
  queue: {
    pending: number;
    running: number;
    oldest_age_seconds: number;
    workspace_limit: number;
    workspace_concurrency: number;
    shared_concurrency: number;
  };
  scheduling: string;
  billing: string;
};
type Key = { id: string; label: string; scope: string; expires_at: number };
export default function CapacityControls({ user }: { user: User }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [keys, setKeys] = useState<Key[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState("Server integration");
  const [scope, setScope] = useState("read");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [secret, setSecret] = useState("");
  async function refresh() {
    setUsage(await api<Usage>("/usage"));
    if (user.role === "owner") setKeys(await api<Key[]>("/auth/keys"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    const timer = setInterval(
      () => refresh().catch((e) => setError(e.message)),
      15000,
    );
    return () => clearInterval(timer);
  }, []);
  async function action(work: () => Promise<void>) {
    setError("");
    setBusy(true);
    try {
      await work();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  const number = (n: number) => n.toLocaleString();
  return (
    <div className="settings-grid account-security">
      <section className="panel settings-panel">
        <h2>Usage and shared capacity</h2>
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}
        {usage ? (
          <>
            <dl className="settings-list">
              <div>
                <dt>Service entitlement</dt>
                <dd>
                  {usage.plan} · scheduling weight {usage.weight}
                </dd>
              </div>
              <div>
                <dt>Your token usage / daily limit</dt>
                <dd>
                  {number(usage.tokens.used)} /{" "}
                  {number(usage.tokens.daily_limit)}
                </dd>
              </div>
              <div>
                <dt>Reserved for in-flight calls</dt>
                <dd>{number(usage.tokens.reserved)} tokens</dd>
              </div>
              <div>
                <dt>Shared tokens used / limit</dt>
                <dd>
                  {number(usage.shared_tokens.used)} /{" "}
                  {number(usage.shared_tokens.daily_limit)}
                </dd>
              </div>
              <div>
                <dt>Queued / active work</dt>
                <dd>
                  {usage.queue.pending} / {usage.queue.running}
                </dd>
              </div>
              <div>
                <dt>Oldest queued job</dt>
                <dd>{usage.queue.oldest_age_seconds.toFixed(1)} s</dd>
              </div>
              <div>
                <dt>Workspace / shared concurrency ceiling</dt>
                <dd>
                  {usage.queue.workspace_concurrency} /{" "}
                  {usage.queue.shared_concurrency}
                </dd>
              </div>
              <div>
                <dt>Source storage</dt>
                <dd>
                  {(usage.storage.bytes / 1048576).toFixed(2)} /{" "}
                  {(usage.storage.limit_bytes / 1048576).toFixed(0)} MiB
                </dd>
              </div>
            </dl>
            <p className="muted">{usage.scheduling}</p>
            <div className="notice">
              <p>{usage.billing}</p>
            </div>
          </>
        ) : (
          <p role="status">Loading capacity…</p>
        )}
      </section>
      {user.role === "owner" && (
        <section className="panel settings-panel">
          <h2>Server API integrations</h2>
          <p className="muted">
            Create a scoped key for your server. Keep it out of browser code.
            Keys expire after 30 days, can be revoked, and cannot administer
            accounts or change plans.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action(async () => {
                const value = await api<{ key: string }>("/auth/keys", {
                  method: "POST",
                  body: JSON.stringify({
                    label,
                    scope,
                    password,
                    code,
                    days: 30,
                  }),
                });
                setSecret(value.key);
                setPassword("");
                setCode("");
              });
            }}
          >
            <label htmlFor="key-label">Integration label</label>
            <input
              id="key-label"
              value={label}
              maxLength={100}
              required
              onChange={(e) => setLabel(e.target.value)}
            />
            <label htmlFor="key-scope">Key permission</label>
            <select
              id="key-scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="read">Read only</option>
              <option value="write">Read and research</option>
            </select>
            <label htmlFor="key-password">Confirm current password</label>
            <input
              id="key-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <label htmlFor="key-code">MFA or recovery code (if enabled)</label>
            <input
              id="key-code"
              value={code}
              autoComplete="one-time-code"
              maxLength={64}
              onChange={(e) => setCode(e.target.value)}
            />
            <button className="button secondary" disabled={busy}>
              Create scoped API key
            </button>
          </form>
          {secret && (
            <div className="notice security-secret">
              <p>
                Save this key in your server's secret store. It will not be
                shown again.
              </p>
              <code>{secret}</code>
              <button className="text-button" onClick={() => setSecret("")}>
                Hide secret
              </button>
            </div>
          )}
          {keys.map((row) => (
            <div className="provider-card" key={row.id}>
              <div>
                <strong>{row.label}</strong>
                <p>
                  {row.scope} · expires{" "}
                  {new Date(row.expires_at * 1000).toLocaleDateString()}
                </p>
              </div>
              <button
                className="text-button"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await api(`/auth/keys/${row.id}`, { method: "DELETE" });
                    setSecret("");
                  })
                }
              >
                Revoke key
              </button>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
