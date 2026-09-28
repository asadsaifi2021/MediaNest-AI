import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { Bird, ShieldCheck } from "lucide-react";
import { supabase, useAuth } from "./auth";
import { configIssue } from "./config";
import { ErrorBox } from "./components";

export function passwordIssue(password: string, confirmation: string) {
  if (password.length < 12)
    return "Use a password with at least 12 characters.";
  if (password.length > 128) return "Use no more than 128 characters.";
  if (password !== confirmation) return "Passwords do not match.";
  return "";
}

export function AuthScreen() {
  const auth = useAuth();
  const { pathname } = useLocation();
  const mode =
    pathname === "/auth/sign-up"
      ? "signup"
      : pathname === "/auth/forgot-password"
        ? "forgot"
        : pathname === "/auth/reset-password"
          ? "reset"
          : pathname === "/auth/callback"
            ? "callback"
            : "signin";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (!cooldown) return;
    const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);
  const callbackUrl = window.location.origin + "/auth/callback";
  const resetUrl = window.location.origin + "/auth/reset-password";
  const heading = {
    signin: "Welcome back.",
    signup: "Create your private archive.",
    forgot: "Forgot your password?",
    reset: "Choose a new password.",
    callback: "Confirm your email.",
  }[mode];
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase || busy) return;
    setError("");
    setMessage("");
    if (mode === "signup" || mode === "reset") {
      const issue = passwordIssue(password, confirmation);
      if (issue) {
        setError(issue);
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (error) throw error;
      } else if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email: email.trim(),
          password,
          options: { emailRedirectTo: callbackUrl },
        });
        if (error) throw error;
        if (!data.session) {
          setMessage(
            "Check your email. If this address can be registered, you’ll receive a confirmation link. Already registered? Sign in or reset your password.",
          );
          setCooldown(60);
        }
        setPassword("");
        setConfirmation("");
      } else if (mode === "forgot") {
        const { error } = await supabase.auth.resetPasswordForEmail(
          email.trim(),
          { redirectTo: resetUrl },
        );
        if (error) throw error;
        setMessage(
          "If an account exists for this email, you’ll receive a password reset link.",
        );
        setCooldown(60);
      } else if (mode === "reset") {
        const { error } = await supabase.auth.updateUser({ password });
        if (error) throw error;
        setPassword("");
        setConfirmation("");
        setSaved(true);
        setMessage(
          "Password updated successfully. You can return to your library.",
        );
      }
    } catch (err) {
      const value = err as { code?: string; message?: string };
      setError(
        value.code === "email_not_confirmed"
          ? "Confirm your email first. You can resend the confirmation below."
          : value.code === "signup_disabled" ||
              /signups? (not allowed|disabled)/i.test(value.message || "")
            ? "New accounts are disabled in Supabase. Ask the archive administrator to enable sign-ups."
            : value.code === "over_email_send_rate_limit" ||
                value.code === "over_request_rate_limit"
              ? "Too many requests. Please wait before trying again."
              : value.message ||
                "Authentication request failed. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function resend() {
    if (!supabase || busy || cooldown) return;
    if (!email.trim()) {
      setError("Enter your email address first.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const { error } = await supabase.auth.resend({
        type: "signup",
        email: email.trim(),
        options: { emailRedirectTo: callbackUrl },
      });
      if (error) throw error;
      setMessage(
        "If confirmation is needed, a new email will arrive shortly. Use the newest link.",
      );
      setCooldown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resend email.");
    } finally {
      setBusy(false);
    }
  }
  if (mode === "callback" && auth.session && !auth.callbackError)
    return <Navigate to="/" replace />;
  const invalidReset =
    mode === "reset" && (!auth.session || Boolean(auth.callbackError));
  return (
    <div className="login">
      <section className="login-story">
        <div className="brand">
          <Bird size={28} />
          <span>
            MediaNest <b>AI</b>
          </span>
        </div>
        <div>
          <span className="eyebrow light">YOUR MEDIA. YOUR STORAGE.</span>
          <h1>
            Life happens.
            <br />
            Keep the good parts.
          </h1>
          <p>
            A private home for your photos, videos, and voices. Your originals
            stay at home.
          </p>
          <div className="login-art">
            <img
              src="/samples/lake.svg"
              alt="Illustrated mountains reflected in a still lake"
            />
            <span>Room for a lifetime of moments.</span>
          </div>
        </div>
        <small>
          <ShieldCheck size={16} /> Your archive belongs to you.
        </small>
      </section>
      <section className="login-form">
        <span className="eyebrow">WELCOME TO MEDIANEST AI</span>
        <h2>{heading}</h2>
        {configIssue && <p role="status">{configIssue}</p>}
        {mode === "callback" || invalidReset ? (
          <>
            <ErrorBox
              error={
                auth.callbackError ||
                "Open the newest email link in the same browser where you requested it."
              }
            />
            <Link to="/auth/forgot-password">Request a password reset</Link>
            <p>
              <Link to="/auth/sign-in">
                Back to sign in / resend confirmation
              </Link>
            </p>
          </>
        ) : (
          <>
            {mode === "signup" && (
              <p className="muted">
                Create an account, confirm your email, and start your own
                archive. This does not give access to another user’s storage.
              </p>
            )}
            {mode === "forgot" && (
              <p className="muted">We’ll send a link to reset your password.</p>
            )}
            {!saved && (
              <form onSubmit={submit}>
                {mode !== "reset" && (
                  <label>
                    Email address
                    <input
                      type="email"
                      autoComplete="username"
                      required
                      maxLength={254}
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      disabled={busy || !supabase}
                    />
                  </label>
                )}
                {mode !== "forgot" && (
                  <>
                    <label>
                      {mode === "reset" ? "New password" : "Password"}
                      <input
                        type={show ? "text" : "password"}
                        autoComplete={
                          mode === "signin"
                            ? "current-password"
                            : "new-password"
                        }
                        required
                        maxLength={128}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        disabled={busy || !supabase}
                      />
                    </label>
                    {mode !== "signin" && (
                      <label>
                        Confirm password
                        <input
                          type={show ? "text" : "password"}
                          autoComplete="new-password"
                          required
                          maxLength={128}
                          value={confirmation}
                          onChange={(e) => setConfirmation(e.target.value)}
                          disabled={busy || !supabase}
                        />
                      </label>
                    )}
                    <button
                      className="text-button"
                      type="button"
                      aria-pressed={show}
                      onClick={() => setShow(!show)}
                    >
                      {show ? "Hide password" : "Show password"}
                    </button>
                    {mode !== "signin" && (
                      <p className="small muted">
                        Use at least 12 characters. Your Supabase project may
                        require additional password rules.
                      </p>
                    )}
                  </>
                )}
                {(error || auth.error) && (
                  <ErrorBox error={error || auth.error} />
                )}
                <button
                  className="primary wide"
                  disabled={
                    busy || !supabase || (mode === "forgot" && cooldown > 0)
                  }
                >
                  {busy
                    ? "Please wait…"
                    : mode === "signin"
                      ? "Sign in"
                      : mode === "signup"
                        ? "Create account"
                        : mode === "forgot"
                          ? cooldown
                            ? `Try again in ${cooldown}s`
                            : "Send reset link"
                          : "Save new password"}
                </button>
              </form>
            )}
            {message && (
              <p role="status" className="notice">
                {message}
              </p>
            )}
            {(mode === "signup" || mode === "forgot") && (
              <p className="small muted">
                Open the email in this same browser and device. Keep using the
                same address ({window.location.origin}); localhost and 127.0.0.1
                are different browser sessions.
              </p>
            )}
            {(mode === "signup" || mode === "signin") && (
              <button
                className="text-button"
                disabled={busy || !supabase || cooldown > 0}
                onClick={() => void resend()}
              >
                {cooldown
                  ? `Resend in ${cooldown}s`
                  : "Resend confirmation email"}
              </button>
            )}
            {mode === "signin" ? (
              <>
                <p>
                  <Link to="/auth/forgot-password">Forgot password?</Link>
                </p>
                <p>
                  New here? <Link to="/auth/sign-up">Create an account</Link>
                </p>
                <div className="separator">
                  <span>OR GET A FEEL FOR IT</span>
                </div>
                <button className="secondary wide" onClick={auth.enterPreview}>
                  Explore sample library
                </button>
              </>
            ) : (
              <p>
                <Link to={saved ? "/" : "/auth/sign-in"}>
                  {saved ? "Go to my library" : "Back to sign in"}
                </Link>
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
