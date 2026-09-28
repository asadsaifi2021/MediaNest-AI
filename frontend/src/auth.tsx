import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createClient, type Session } from "@supabase/supabase-js";
import { useQueryClient } from "@tanstack/react-query";
import { configIssue, publicKey, supabaseUrl, demoOnly } from "./config";

export const supabase = configIssue
  ? null
  : createClient(supabaseUrl, publicKey, {
      auth: {
        flowType: "pkce",
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
    });
type Auth = {
  session: Session | null;
  loading: boolean;
  preview: boolean;
  error: string;
  callbackError: string;
  enterPreview: () => void;
  leavePreview: () => void;
  signOut: () => Promise<void>;
};
const AuthContext = createContext<Auth | null>(null);
// Shared promise avoids consuming a one-use code twice under React StrictMode.
let callbackPromise: Promise<string> | undefined;
function finishCallback(): Promise<string> {
  if (callbackPromise) return callbackPromise;
  callbackPromise = (async () => {
    const url = new URL(window.location.href);
    if (!["/auth/callback", "/auth/reset-password"].includes(url.pathname))
      return "";
    const hash = new URLSearchParams(url.hash.slice(1));
    const code = url.searchParams.get("code");
    const failed = url.searchParams.has("error") || hash.has("error");
    if (!code && !failed)
      return url.pathname === "/auth/callback"
        ? "This confirmation link is incomplete. Request a new email."
        : "";
    // Remove one-use credentials/error details from browser history immediately.
    window.history.replaceState(window.history.state, "", url.pathname);
    if (failed || !code)
      return "This email link is invalid or expired. Request a new email.";
    if (!supabase) return "Supabase is not configured.";
    try {
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      return error
        ? "This link could not be verified. Open the newest email in the same browser and device that requested it, or request another link."
        : "";
    } catch {
      return "Unable to verify the email link. Check your connection and request a new link.";
    }
  })();
  return callbackPromise;
}
export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(Boolean(supabase));
  const [preview, setPreview] = useState(demoOnly);
  const [error, setError] = useState("");
  const [callbackError, setCallbackError] = useState("");
  const user = useRef<string | null>(null);
  useEffect(() => {
    if (!supabase) return;
    let active = true;
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, next) => {
      if (!active) return;
      if (user.current !== (next?.user.id ?? null)) {
        void client.cancelQueries();
        client.clear();
      }
      user.current = next?.user.id ?? null;
      setSession(next);
      if (next) setError("");
      if (next) setPreview(false);
    });
    finishCallback()
      .then(async (callbackIssue) => {
        const { data, error } = await supabase.auth.getSession();
        if (active) {
          setCallbackError(callbackIssue);
          if (error)
            setError("Unable to restore your session. Please sign in again.");
          setSession(data.session);
          setLoading(false);
        }
      })
      .catch(() => {
        if (active) {
          setError("Unable to restore your session. Please sign in again.");
          setLoading(false);
        }
      });
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, [client]);
  const clear = () => {
    void client.cancelQueries();
    client.clear();
  };
  return (
    <AuthContext.Provider
      value={{
        session,
        loading,
        preview,
        error,
        callbackError,
        enterPreview: () => {
          clear();
          setPreview(true);
        },
        leavePreview: () => {
          clear();
          setPreview(demoOnly);
        },
        signOut: async () => {
          clear();
          setPreview(demoOnly);
          const result = await supabase?.auth
            .signOut({ scope: "local" })
            .catch(() => ({ error: true }));
          if (result?.error) {
            setError("Sign out could not be completed. Please try again.");
            return;
          }
          setSession(null);
          setError("");
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("Auth provider missing");
  return context;
}
