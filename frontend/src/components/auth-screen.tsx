"use client";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  FlaskConical,
  Layers3,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/client";

export default function AuthScreen({
  demoEnabled,
  busy,
  error,
  signIn,
}: {
  demoEnabled: boolean;
  busy: boolean;
  error: string;
  signIn: (email: string, password: string, code?: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [view, setView] = useState("login");
  const [token, setToken] = useState("");
  const [workspace, setWorkspace] = useState("My research workspace");
  const [options, setOptions] = useState({
    signup: "invite",
    email_recovery: false,
  });
  const [localBusy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [localError, setError] = useState("");
  useEffect(() => {
    api<typeof options>("/auth/options")
      .then(setOptions)
      .catch(() => {});
    const acceptLink = () => {
      const match = window.location.hash.match(
        /^#(invite|signup|reset)=([A-Za-z0-9_-]{32,128})$/,
      );
      if (match) {
        setView(match[1]);
        setToken(match[2]);
        setMessage("");
        setError("");
        setPassword("");
        window.history.replaceState(null, "", window.location.pathname);
      }
    };
    acceptLink();
    window.addEventListener("hashchange", acceptLink);
    return () => window.removeEventListener("hashchange", acceptLink);
  }, []);
  const change = (value: string) => {
    setView(value);
    setMessage("");
    setError("");
    setPassword("");
    setCode("");
  };
  async function submit() {
    setError("");
    setMessage("");
    if (view === "login") {
      await signIn(email, password, code);
      return;
    }
    setBusy(true);
    try {
      if (view === "register" || view === "forgot") {
        const result = await api<{ message: string }>(
          `/auth/${view === "register" ? "register" : "forgot-password"}`,
          { method: "POST", body: JSON.stringify({ email }) },
        );
        setMessage(result.message);
      } else {
        await api("/auth/redeem", {
          method: "POST",
          body: JSON.stringify({ token, password, workspace }),
        });
        setToken("");
        change("login");
        setMessage("Account updated. Sign in with your password.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Please retry.");
    } finally {
      setBusy(false);
    }
  }
  const redeem = ["invite", "signup", "reset"].includes(view);
  return (
    <div className="login-shell">
      <div className="login-intro">
        <div className="brand">
          <span className="brand-mark">
            <Layers3 size={21} />
          </span>
          <span>
            quarry<span className="brand-dot">.</span>
          </span>
        </div>
        <div>
          <span className="eyebrow">ENGINEERING RESEARCH, GROUNDED.</span>
          <h1>
            Good decisions
            <br />
            leave a trail.
          </h1>
          <p>
            From a question to an inspectable brief.
            <br />
            Your sources. Your tools. Every step in view.
          </p>
          <div className="login-features">
            <span>
              <BookOpen size={17} /> Evidence you can inspect
            </span>
            <span>
              <FlaskConical size={17} /> Retrieval you can measure
            </span>
            <span>
              <ShieldCheck size={17} /> Execution you can trust
            </span>
          </div>
        </div>
        <small>QUARRY / RESEARCH WORKSPACE</small>
      </div>
      <div className="login-form-wrap">
        <form
          className="login-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <span className="pill muted-pill">YOUR WORKSPACE AWAITS</span>
          <h2>
            {view === "login"
              ? "Welcome to Quarry."
              : view === "forgot"
                ? "Recover your account."
                : view === "register"
                  ? "Create your workspace."
                  : view === "reset"
                    ? "Set a new password."
                    : "Accept your invitation."}
          </h2>
          <p>
            {redeem
              ? "Choose a unique passphrase of at least 15 characters."
              : view === "login"
                ? "Sign in and pick up the thread."
                : "Check your email to continue securely."}
          </p>
          {(localError || error) && (
            <div className="error-banner" role="alert">
              {localError || error}
            </div>
          )}
          {message && (
            <p role="status" className="notice">
              {message}
            </p>
          )}
          {!redeem && (
            <>
              <label htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
              />
            </>
          )}
          {(view === "login" || redeem) && (
            <>
              <label htmlFor="password">
                {redeem ? "New password" : "Password"}
              </label>
              <input
                id="password"
                type="password"
                autoComplete={redeem ? "new-password" : "current-password"}
                minLength={redeem ? 15 : 1}
                maxLength={redeem ? 128 : 256}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </>
          )}
          {view === "signup" && (
            <>
              <label htmlFor="workspace">Workspace name</label>
              <input
                id="workspace"
                maxLength={120}
                required
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
              />
            </>
          )}
          {view === "login" && (
            <>
              <label htmlFor="otp">
                Verification or recovery code <small>(if MFA is enabled)</small>
              </label>
              <input
                id="otp"
                autoComplete="one-time-code"
                maxLength={64}
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </>
          )}
          <button className="button primary" disabled={busy || localBusy}>
            {busy || localBusy ? (
              <Loader2 className="spin" size={17} />
            ) : (
              <>
                {view === "login"
                  ? "Open workspace"
                  : redeem
                    ? "Save password"
                    : "Send secure link"}{" "}
                <ArrowRight size={17} />
              </>
            )}
          </button>
          {view === "login" ? (
            <div className="auth-links">
              {options.email_recovery && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => change("forgot")}
                >
                  Forgot password?
                </button>
              )}
              {options.signup === "public" && (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => change("register")}
                >
                  Create an account
                </button>
              )}
              {options.signup === "invite" && (
                <small>
                  New here? Ask your workspace owner for an invitation.
                </small>
              )}
            </div>
          ) : (
            <button
              type="button"
              className="text-button"
              onClick={() => change("login")}
            >
              Back to sign in
            </button>
          )}
          {demoEnabled && view === "login" && (
            <>
              <div className="login-divider">
                <span>or explore the local sample</span>
              </div>
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => signIn("demo@quarry.local", "quarry-demo-local")}
              >
                Explore sample workspace <ArrowRight size={16} />
              </button>
              <small className="muted">
                Synthetic engineering documents · local retrieval · no API key
                needed
              </small>
            </>
          )}
          <div className="login-security">
            <ShieldCheck size={14} /> Revocable sessions. Private source
            storage.
          </div>
        </form>
      </div>
    </div>
  );
}
