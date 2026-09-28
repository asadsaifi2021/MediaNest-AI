import { useEffect, useState } from "react";
import { request } from "./api";
import { useAuth } from "./auth";

export function LocalPlayer({
  id,
  type,
}: {
  id: string;
  type: "video" | "audio";
}) {
  const { session } = useAuth();
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    setUrl("");
    setError("");
    const connect = async () => {
      try {
        const grant = await request<{ token: string; url: string }>(
          `/api/v1/media/${id}/access-grant?kind=playback`,
          session.access_token,
          { method: "POST", signal: controller.signal },
        );
        const target = new URL(grant.url);
        if (
          target.protocol !== "https:" &&
          !(
            target.protocol === "http:" &&
            ["localhost", "127.0.0.1"].includes(target.hostname)
          )
        )
          throw new Error("Playback requires HTTPS.");
        const response = await fetch(new URL("/playback-session", target), {
          method: "POST",
          headers: { Authorization: "Bearer " + grant.token },
          credentials: "include",
          redirect: "error",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok)
          throw new Error("Could not authorize local playback.");
        if (!controller.signal.aborted) {
          setUrl(target.href);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Playback unavailable.");
      }
    };
    void connect();
    const renew = window.setInterval(() => void connect(), 60000);
    return () => {
      controller.abort();
      clearInterval(renew);
    };
  }, [id, session?.access_token, attempt]);
  const props = {
    src: url || undefined,
    controls: true,
    crossOrigin: "use-credentials" as const,
    preload: "metadata",
    style: { width: "100%" },
    onError: () =>
      setError(
        "Storage is offline, playback expired, or cookies were blocked. Use the same private HTTPS hostname for the app and storage, then retry.",
      ),
  };
  return (
    <section>
      <h3>Local playback</h3>
      {url && (type === "video" ? <video {...props} /> : <audio {...props} />)}
      {!url && !error && <p role="status">Connecting to local playback…</p>}
      {error && <p role="alert">{error}</p>}
      <button className="secondary" onClick={() => setAttempt((v) => v + 1)}>
        Reconnect playback
      </button>
    </section>
  );
}
