import { useEffect, useRef, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { supabase, useAuth } from "./auth";
import { passwordIssue } from "./auth-pages";
import { Empty, ErrorBox } from "./components";
import type { User } from "@supabase/supabase-js";

export function Account() {
  const { session, preview } = useAuth();
  const query = useQuery({
    queryKey: ["account", session?.user.id],
    enabled: Boolean(session && !preview && supabase),
    queryFn: async () => {
      const { data, error } = await supabase!.auth.getUser();
      if (error) throw error;
      if (data.user.id !== session?.user.id)
        throw new Error("Account changed. Refresh the page.");
      return data.user;
    },
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR ACCOUNT</span>
          <h1>
            Make yourself at home<span>.</span>
          </h1>
          <p>Manage your profile, sign-in details, and sessions.</p>
        </div>
      </div>
      {preview ? (
        <Empty title="Sign in to manage your account">
          Sample mode cannot change account settings.
        </Empty>
      ) : query.isPending ? (
        <p role="status">Loading your account…</p>
      ) : query.error ? (
        <ErrorBox error={query.error} retry={() => void query.refetch()} />
      ) : (
        query.data && (
          <AccountForms
            key={query.data.id}
            user={query.data}
            refresh={() => void query.refetch()}
          />
        )
      )}
    </>
  );
}

function AccountForms({ user, refresh }: { user: User; refresh: () => void }) {
  const auth = useAuth();
  const cache = useQueryClient();
  const [name, setName] = useState(
    typeof user.user_metadata.full_name === "string"
      ? user.user_metadata.full_name
      : "",
  );
  const [email, setEmail] = useState("");
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [nonce, setNonce] = useState("");
  const [needsNonce, setNeedsNonce] = useState(false);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const [feedback, setFeedback] = useState<{
    section: string;
    error?: string;
    message?: string;
  }>({ section: "" });
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!cooldown) return;
    const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);
  async function action(section: string, work: () => Promise<string>) {
    if (!supabase || busy) return;
    setBusy(section);
    setFeedback({ section });
    try {
      const { data, error } = await supabase.auth.getUser();
      if (error) throw error;
      if (data.user.id !== user.id)
        throw new Error("Account changed. Reload before making changes.");
      const message = await work();
      if (mounted.current) setFeedback({ section, message });
    } catch (err) {
      if (!mounted.current) return;
      const e = err as { code?: string; message?: string };
      if (
        e.code === "reauthentication_needed" ||
        /reauthentication/i.test(e.message || "")
      )
        setNeedsNonce(true);
      setFeedback({
        section,
        error: e.message || "Could not save the change. Try again.",
      });
    } finally {
      if (mounted.current) setBusy("");
    }
  }
  async function update(
    attributes: Parameters<
      NonNullable<typeof supabase>["auth"]["updateUser"]
    >[0],
  ) {
    const { data, error } = await supabase!.auth.updateUser(attributes, {
      emailRedirectTo: window.location.origin + "/auth/callback",
    });
    if (error) throw error;
    if (mounted.current) cache.setQueryData(["account", user.id], data.user);
    return data.user;
  }
  function status(section: string) {
    if (feedback.section !== section) return null;
    return feedback.error ? (
      <ErrorBox error={feedback.error} />
    ) : feedback.message ? (
      <p className="notice" role="status">
        {feedback.message}
      </p>
    ) : null;
  }
  function submit(
    event: FormEvent,
    section: string,
    work: () => Promise<string>,
  ) {
    event.preventDefault();
    void action(section, work);
  }
  const disabled = Boolean(busy);
  return (
    <div className="account-settings">
      <section className="panel">
        <h2>Profile</h2>
        <form
          onSubmit={(e) =>
            submit(e, "profile", async () => {
              if (name.trim().length > 100)
                throw new Error("Use no more than 100 characters.");
              await update({ data: { full_name: name.trim() } });
              return "Profile saved.";
            })
          }
        >
          <label>
            Display name
            <input
              autoComplete="name"
              maxLength={100}
              value={name}
              disabled={disabled}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <p className="small muted">
            Optional. This changes your display name, not your account ownership
            or storage permissions.
          </p>
          <button className="primary" disabled={disabled}>
            {busy === "profile" ? "Saving…" : "Save profile"}
          </button>
        </form>
        {status("profile")}
        <dl className="account-facts">
          <dt>Current email</dt>
          <dd>{user.email || "Not provided"}</dd>
          <dt>Email status</dt>
          <dd>{user.email_confirmed_at ? "Confirmed" : "Not confirmed"}</dd>
          <dt>Account created</dt>
          <dd>{new Date(user.created_at).toLocaleDateString()}</dd>
          <dt>Account ID</dt>
          <dd>{user.id}</dd>
        </dl>
        <button className="text-button" disabled={disabled} onClick={refresh}>
          Refresh account details
        </button>
      </section>
      <section className="panel">
        <h2>Email address</h2>
        <p className="muted">
          Supabase may require confirmation from both your current and new email
          addresses. Your current address stays active until confirmation
          finishes.
        </p>
        {user.new_email && (
          <p role="status">
            Pending email change: {user.new_email}. Check your inboxes, then
            refresh account details.
          </p>
        )}
        <form
          onSubmit={(e) =>
            submit(e, "email", async () => {
              const clean = email.trim();
              if (clean.toLowerCase() === user.email?.toLowerCase())
                throw new Error("Enter a different email address.");
              const result = await update({ email: clean });
              setEmail("");
              return result.email === clean
                ? "Email address updated."
                : "Email change requested. Follow the confirmation links in your inboxes.";
            })
          }
        >
          <label>
            New email address
            <input
              type="email"
              autoComplete="email"
              required
              maxLength={254}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={disabled}
            />
          </label>
          <button className="primary" disabled={disabled}>
            {busy === "email" ? "Requesting…" : "Request email change"}
          </button>
        </form>
        {status("email")}
      </section>
      <section className="panel">
        <h2>Password</h2>
        <form
          onSubmit={(e) =>
            submit(e, "password", async () => {
              const issue = passwordIssue(password, confirmation);
              if (issue) throw new Error(issue);
              if (current === password)
                throw new Error("Choose a different password.");
              try {
                await update({
                  password,
                  current_password: current,
                  ...(nonce.trim() ? { nonce: nonce.trim() } : {}),
                });
                setNeedsNonce(false);
                setNonce("");
                return "Password updated. Use the new password next time you sign in.";
              } finally {
                setCurrent("");
                setPassword("");
                setConfirmation("");
              }
            })
          }
        >
          <label>
            Current password
            <input
              type={show ? "text" : "password"}
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              disabled={disabled}
            />
          </label>
          <label>
            New password
            <input
              type={show ? "text" : "password"}
              autoComplete="new-password"
              required
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={disabled}
            />
          </label>
          <label>
            Confirm new password
            <input
              type={show ? "text" : "password"}
              autoComplete="new-password"
              required
              maxLength={128}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              disabled={disabled}
            />
          </label>
          <button
            type="button"
            className="text-button"
            aria-pressed={show}
            onClick={() => setShow(!show)}
          >
            {show ? "Hide passwords" : "Show passwords"}
          </button>
          <p className="small muted">
            At least 12 characters. Passwords are sent directly to Supabase, not
            stored in MediaNest metadata.
          </p>
          {needsNonce && (
            <label>
              Email verification code
              <input
                autoComplete="one-time-code"
                value={nonce}
                onChange={(e) => setNonce(e.target.value)}
                disabled={disabled}
                required
              />
            </label>
          )}
          <button className="primary" disabled={disabled}>
            {busy === "password" ? "Updating…" : "Update password"}
          </button>
        </form>
        {status("password")}
        {needsNonce && (
          <button
            className="secondary"
            disabled={disabled || cooldown > 0}
            onClick={() =>
              void action("code", async () => {
                const { error } = await supabase!.auth.reauthenticate();
                if (error) throw error;
                setCooldown(60);
                return "Verification code sent. Enter it above, re-enter your passwords, and save.";
              })
            }
          >
            {cooldown ? `Send again in ${cooldown}s` : "Send verification code"}
          </button>
        )}
        {status("code")}
        <p>
          <Link to="/auth/forgot-password">Forgot your current password?</Link>
        </p>
      </section>
      <section className="panel">
        <h2>Sessions and privacy</h2>
        <p>
          Sign out of this browser or revoke other sessions. Already-issued
          access tokens may remain valid until they expire; this is not an
          immediate wipe of other devices.
        </p>
        <div className="account-actions">
          <button
            className="secondary"
            disabled={disabled}
            onClick={() => void auth.signOut()}
          >
            Sign out of this browser
          </button>
          <button
            className="secondary"
            disabled={disabled}
            onClick={() => {
              if (
                window.confirm(
                  "Sign out of all other sessions? This browser will stay signed in.",
                )
              ) {
                void action("sessions", async () => {
                  const { error } = await supabase!.auth.signOut({
                    scope: "others",
                  });
                  if (error) throw error;
                  return "Other sessions revoked. This browser is still signed in.";
                });
              }
            }}
          >
            Sign out other sessions
          </button>
        </div>
        {status("sessions")}
        <p className="small muted">
          Account settings do not delete media, disable storage nodes, or share
          your archive. Account deletion and a device-by-device session list are
          not available here.
        </p>
      </section>
    </div>
  );
}
