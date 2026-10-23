"use client";
import { useEffect, useState } from "react";
import { api, User } from "@/lib/client";
type Security = {
  mfa_enabled: boolean;
  sessions: {
    id: string;
    created_at: number;
    last_seen_at: number;
    current: boolean;
  }[];
};
type Member = { id: string; email: string; role: string; disabled: boolean };

export default function AccountSecurity({
  user,
  signOut,
}: {
  user: User;
  signOut: () => void;
}) {
  const [status, setStatus] = useState<Security | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(
    null,
  );
  const [codes, setCodes] = useState<string[]>([]);
  const [inviteEmail, setEmail] = useState("");
  const [role, setRole] = useState("editor");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function refresh() {
    setStatus(await api<Security>("/auth/security"));
    if (user.role === "owner") setMembers(await api<Member[]>("/members"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  const credential = { password, code };
  return (
    <div className="settings-grid account-security">
      <section className="panel settings-panel">
        <h2>Account security</h2>
        <p className="muted">
          {user.email} · {user.role}. Changes require your current password. MFA
          codes can be used once.
        </p>
        {error && (
          <div role="alert" className="error-banner">
            {error}
          </div>
        )}
        {notice && <p role="status">{notice}</p>}
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <label htmlFor="security-code">Authenticator or recovery code</label>
        <input
          id="security-code"
          autoComplete="one-time-code"
          value={code}
          maxLength={64}
          onChange={(e) => setCode(e.target.value)}
        />
        <div className="security-actions">
          <strong>
            Authenticator MFA: {status?.mfa_enabled ? "Enabled" : "Disabled"}
          </strong>
          {status?.mfa_enabled ? (
            <button
              className="button secondary"
              disabled={busy || !password || !code}
              onClick={() =>
                action(async () => {
                  await api("/auth/mfa/disable", {
                    method: "POST",
                    body: JSON.stringify(credential),
                  });
                  setNotice("MFA disabled. Other sessions were revoked.");
                  setCode("");
                })
              }
            >
              Disable MFA
            </button>
          ) : (
            <button
              className="button secondary"
              disabled={busy || !password}
              onClick={() =>
                action(async () => {
                  setSetup(
                    await api("/auth/mfa/setup", {
                      method: "POST",
                      body: JSON.stringify(credential),
                    }),
                  );
                  setCodes([]);
                })
              }
            >
              Set up authenticator
            </button>
          )}
        </div>
        {setup && (
          <div className="notice security-secret">
            <p>
              Enter this setup key in your authenticator app. Keep it private.
            </p>
            <code>{setup.secret}</code>
            <button
              className="button primary"
              disabled={busy || !code}
              onClick={() =>
                action(async () => {
                  const result = await api<{ recovery_codes: string[] }>(
                    "/auth/mfa/confirm",
                    { method: "POST", body: JSON.stringify(credential) },
                  );
                  setCodes(result.recovery_codes);
                  setSetup(null);
                  setCode("");
                })
              }
            >
              Verify and enable MFA
            </button>
          </div>
        )}
        {codes.length > 0 && (
          <div className="notice security-secret" role="status">
            <p>
              Save these recovery codes offline now. Each works once; they will
              not be shown again.
            </p>
            {codes.map((value) => (
              <code key={value}>{value}</code>
            ))}
            <button className="button secondary" onClick={() => setCodes([])}>
              I saved my recovery codes
            </button>
          </div>
        )}
        <label htmlFor="new-password">New password (15–128 characters)</label>
        <input
          id="new-password"
          type="password"
          autoComplete="new-password"
          minLength={15}
          maxLength={128}
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        <button
          className="button secondary"
          disabled={busy || !password || newPassword.length < 15}
          onClick={() =>
            action(async () => {
              await api("/auth/password", {
                method: "POST",
                body: JSON.stringify({
                  ...credential,
                  new_password: newPassword,
                }),
              });
              signOut();
            })
          }
        >
          Change password and sign out all sessions
        </button>
      </section>
      <section className="panel settings-panel">
        <h2>Active sessions</h2>
        <p className="muted">
          Sessions expire after seven days or twelve hours of inactivity.
          Revocation applies across every API replica.
        </p>
        {status?.sessions.map((row) => (
          <div className="provider-card" key={row.id}>
            <div>
              <strong>
                {row.current ? "This browser" : "Another session"}
              </strong>
              <p>
                Last active {new Date(row.last_seen_at * 1000).toLocaleString()}
              </p>
            </div>
            <button
              className="text-button"
              disabled={busy}
              onClick={() =>
                action(async () => {
                  await api(`/auth/sessions/${row.id}`, { method: "DELETE" });
                  if (row.current) signOut();
                })
              }
            >
              Revoke
            </button>
          </div>
        ))}
        {user.role === "owner" && (
          <>
            <h2>Workspace access</h2>
            <p className="muted">
              Invitations expire after 24 hours and can be accepted once. Share
              links privately with the named recipient.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action(async () => {
                  const result = await api<{ link: string; delivery: string }>(
                    "/invitations",
                    {
                      method: "POST",
                      body: JSON.stringify({ email: inviteEmail, role }),
                    },
                  );
                  setLink(result.link);
                  setNotice(
                    result.delivery === "queued"
                      ? "Invitation queued for email delivery."
                      : "Invitation created. Share the private link with the recipient.",
                  );
                });
              }}
            >
              <label htmlFor="invite-email">Invite email</label>
              <input
                id="invite-email"
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setEmail(e.target.value)}
              />
              <label htmlFor="invite-role">Permission</label>
              <select
                id="invite-role"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                <option value="editor">Editor</option>
                <option value="viewer">Viewer</option>
              </select>
              <button className="button secondary" disabled={busy}>
                Create invitation
              </button>
            </form>
            {link && (
              <div className="notice security-secret">
                <label htmlFor="private-invite">Private invitation link</label>
                <input id="private-invite" readOnly value={link} />
                <button className="text-button" onClick={() => setLink("")}>
                  Hide link
                </button>
              </div>
            )}
            {members.map((member) => (
              <div className="provider-card" key={member.id}>
                <div>
                  <strong>{member.email}</strong>
                  <p>
                    {member.role}
                    {member.disabled ? " · disabled" : ""}
                  </p>
                </div>
                {member.role !== "owner" && (
                  <>
                    <select
                      aria-label={`Permission for ${member.email}`}
                      disabled={busy}
                      value={member.role}
                      onChange={(e) =>
                        action(async () => {
                          await api(`/members/${member.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({
                              role: e.target.value,
                              disabled: member.disabled,
                            }),
                          });
                        })
                      }
                    >
                      <option value="editor">Editor</option>
                      <option value="viewer">Viewer</option>
                    </select>
                    <button
                      className="text-button"
                      disabled={busy}
                      onClick={() =>
                        action(async () => {
                          await api(`/members/${member.id}`, {
                            method: "PATCH",
                            body: JSON.stringify({
                              role: member.role,
                              disabled: !member.disabled,
                            }),
                          });
                        })
                      }
                    >
                      {member.disabled ? "Enable" : "Disable"}
                    </button>
                  </>
                )}
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  );
}
