import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "./auth";
import { request } from "./api";
import type { Media } from "./types";

export function TagEditor({ media }: { media: Media }) {
  const { session } = useAuth();
  const cache = useQueryClient();
  const [text, setText] = useState(media.tags.join(", "));
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const tags = text
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      if (tags.length > 50 || tags.some((t) => t.length > 100))
        throw new Error("Use at most 50 tags, each up to 100 characters.");
      const updated = await request<Media>(
        `/api/v1/media/${media.id}/tags`,
        session?.access_token,
        { method: "POST", body: JSON.stringify({ tags }) },
      );
      setText(updated.tags.join(", "));
      await cache.invalidateQueries({ queryKey: ["media"] });
      await cache.invalidateQueries({ queryKey: ["media-detail"] });
      setMessage("Tags saved.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not save tags.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={save}>
      <label>
        Tags (separate with commas)
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
        />
      </label>
      <button className="secondary" disabled={busy}>
        {busy ? "Saving…" : "Save tags"}
      </button>
      {message && <p role="status">{message}</p>}
      {!!media.ai_tags?.length && (
        <p>
          AI suggestions: {media.ai_tags.join(", ")}. Copy any you want into
          your tags.
        </p>
      )}
    </form>
  );
}
