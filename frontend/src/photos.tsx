import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "./auth";
import { request } from "./api";

type Grant = { token: string; url: string };

async function localFetch(grant: Grant, options: RequestInit = {}) {
  const url = new URL(grant.url);
  if (
    url.protocol !== "https:" &&
    !(
      url.protocol === "http:" &&
      ["127.0.0.1", "localhost"].includes(url.hostname)
    )
  ) {
    throw new Error("Storage requires HTTPS except on this PC.");
  }
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      redirect: "error",
      cache: "no-store",
      credentials: "omit",
      headers: { ...options.headers, Authorization: "Bearer " + grant.token },
    });
  } catch {
    throw new Error(
      "Cannot reach local storage. Start the PC storage service and allow browser local-network access if prompted.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "Local file request failed.",
    );
  }
  return response;
}

export function PhotoUpload({ done }: { done: () => void }) {
  const { session, preview } = useAuth();
  const cache = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [id, setId] = useState("");
  const [node, setNode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const nodes = useQuery({
    queryKey: ["upload-nodes", session?.user.id],
    enabled: Boolean(session && !preview),
    queryFn: ({ signal }) =>
      request<
        { id: string; display_name: string; disabled_at: string | null }[]
      >("/api/v1/storage-nodes?limit=100", session?.access_token, { signal }),
  });
  const available = nodes.data?.filter((n) => !n.disabled_at) ?? [];
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || !session) return;
    setBusy(true);
    setError("");
    try {
      const maximum = file.type.startsWith("image/") ? 20 : 256;
      if (file.size < 1 || file.size > maximum * 1024 * 1024)
        throw new Error(`Choose a file no larger than ${maximum} MiB.`);
      if (
        ![
          "image/jpeg",
          "image/png",
          "image/webp",
          "video/mp4",
          "video/webm",
          "video/quicktime",
          "audio/mpeg",
          "audio/mp4",
          "audio/wav",
          "audio/x-wav",
          "audio/flac",
          "audio/ogg",
        ].includes(file.type)
      )
        throw new Error(
          "Unsupported media format. Try JPEG, PNG, WebP, MP4, WebM, MOV, MP3, M4A, WAV, FLAC, or OGG.",
        );
      const grant = await request<Grant>(
        `/api/v1/storage-nodes/${node || available[0]?.id}/upload-grant`,
        session.access_token,
        {
          method: "POST",
          body: JSON.stringify({
            media_id: id,
            filename: file.name,
            byte_size: file.size,
            content_type: file.type,
          }),
        },
      );
      await localFetch(grant, {
        method: "POST",
        body: file,
        signal: AbortSignal.timeout(900000),
        headers: { "Content-Type": file.type },
      });
      await cache.invalidateQueries({ queryKey: ["media"] });
      done();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Upload failed. Retry with the same photo.",
      );
    } finally {
      setBusy(false);
    }
  }
  if (preview)
    return (
      <p>
        No file will be selected or uploaded in sample mode. Sign in to upload a
        photo.
      </p>
    );
  return (
    <form onSubmit={submit}>
      <p>
        Photos up to 20 MiB; video and audio up to 256 MiB. Originals,
        thumbnails, and playback copies stay on your PC. Video/audio conversion
        requires FFmpeg and can take several minutes. Keep this window open
        until it finishes.
      </p>
      {nodes.isPending && <p role="status">Loading storage registrations…</p>}
      {nodes.error && <p role="alert">{nodes.error.message}</p>}
      <label>
        Upload to
        <select
          value={node || available[0]?.id || ""}
          onChange={(e) => setNode(e.target.value)}
          disabled={busy}
          required
        >
          {!available.length && (
            <option value="">Register storage in Connections first</option>
          )}
          {available.map((n) => (
            <option key={n.id} value={n.id}>
              {n.display_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Media file
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,video/mp4,video/webm,video/quicktime,audio/mpeg,audio/mp4,audio/wav,audio/x-wav,audio/flac,audio/ogg"
          required
          disabled={busy}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setId(crypto.randomUUID());
            setError("");
          }}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      {error && (
        <p className="small muted">
          Retry without changing the file to reuse this upload ID. Saved local
          files are preserved if metadata sync fails.
        </p>
      )}
      <button className="primary" disabled={busy || !file || !available.length}>
        {busy ? "Saving and preparing media…" : "Upload media"}
      </button>
    </form>
  );
}

export function useLocalPhoto(
  mediaId: string,
  enabled: boolean,
  kind = "thumbnail",
  faceId?: string,
) {
  const { session } = useAuth();
  const [state, setState] = useState<{ url?: string; error?: string }>({});
  useEffect(() => {
    setState({});
    if (!enabled || !session) return;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    let objectUrl: string | undefined;
    let active = true;
    void (async () => {
      try {
        const grant = await request<Grant>(
          faceId
            ? `/api/v1/faces/${faceId}/preview-grant`
            : `/api/v1/media/${mediaId}/access-grant?kind=${kind}`,
          session.access_token,
          { method: "POST", signal: controller.signal },
        );
        const response = await localFetch(grant, { signal: controller.signal });
        const blob = await response.blob();
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl });
      } catch (e) {
        if (active)
          setState({
            error: e instanceof Error ? e.message : "Local preview unavailable",
          });
      } finally {
        clearTimeout(timeout);
      }
    })();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timeout);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [mediaId, enabled, kind, faceId, session?.access_token, session?.user.id]);
  return state;
}

export function OriginalPhoto({ id }: { id: string }) {
  const [show, setShow] = useState(false);
  const photo = useLocalPhoto(id, show, "original");
  return (
    <section>
      <button className="secondary" onClick={() => setShow(!show)}>
        {show ? "Hide original photo" : "View original photo"}
      </button>
      {show && !photo.url && !photo.error && (
        <p role="status">Loading from your PC…</p>
      )}
      {show && photo.error && <p role="alert">{photo.error}</p>}
      {photo.url && (
        <img
          src={photo.url}
          alt="Original photo"
          style={{ width: "100%", height: "auto" }}
        />
      )}
    </section>
  );
}
