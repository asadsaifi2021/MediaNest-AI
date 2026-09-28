import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "./auth";
import { request } from "./api";
import { useLocalPhoto } from "./photos";
import type { FaceMatch, Media } from "./types";

export function IndexControls({ media }: { media: Media }) {
  const { session } = useAuth();
  const cache = useQueryClient();
  const [objects, setObjects] = useState(true);
  const [transcription, setTranscription] = useState(true);
  const [faces, setFaces] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const status = useQuery({
    queryKey: ["index-status", session?.user.id, media.id],
    queryFn: () =>
      request<Media>(`/api/v1/media/${media.id}`, session?.access_token),
    refetchInterval: (q) =>
      q.state.data?.ai_status === "queued" ? 5000 : false,
  });
  async function action(forget = false) {
    if (
      forget &&
      !window.confirm(
        "Delete face embeddings for this file and cancel pending indexing?",
      )
    )
      return;
    setBusy(true);
    setMessage("");
    try {
      await request(
        `/api/v1/media/${media.id}/${forget ? "forget-faces" : "index"}`,
        session?.access_token,
        {
          method: "POST",
          body: forget
            ? undefined
            : JSON.stringify({
                objects: objects && media.file_type !== "audio",
                transcription: transcription && media.file_type !== "image",
                faces: faces && media.file_type !== "audio",
              }),
        },
      );
      setMessage(
        forget
          ? "Face embeddings removed."
          : "Queued. Keep the local AI worker running.",
      );
      await cache.invalidateQueries({ queryKey: ["index-status"] });
      await cache.invalidateQueries({ queryKey: ["faces"] });
      await cache.invalidateQueries({ queryKey: ["face-groups"] });
      await cache.invalidateQueries({ queryKey: ["media"] });
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section>
      <h3>Local AI processing</h3>
      <p>
        Status: {status.data?.ai_status || media.ai_status || "not_requested"}
      </p>
      {status.data?.ai_message && <p role="alert">{status.data.ai_message}</p>}
      {status.error && <p role="alert">{status.error.message}</p>}
      {!!status.data?.ai_tags?.length && (
        <p>Detected objects: {status.data.ai_tags.join(", ")}</p>
      )}
      {status.data?.transcription && (
        <p className="transcript">{status.data.transcription}</p>
      )}
      {media.file_type !== "audio" && (
        <label>
          <input
            type="checkbox"
            checked={objects}
            onChange={(e) => setObjects(e.target.checked)}
          />{" "}
          Detect objects with YOLOv8
        </label>
      )}
      {media.file_type !== "image" && (
        <label>
          <input
            type="checkbox"
            checked={transcription}
            onChange={(e) => setTranscription(e.target.checked)}
          />{" "}
          Transcribe speech locally
        </label>
      )}
      {media.file_type !== "audio" && (
        <label>
          <input
            type="checkbox"
            checked={faces}
            onChange={(e) => setFaces(e.target.checked)}
          />{" "}
          I consent to face indexing for this file and storing its biometric
          vectors in my private metadata database
        </label>
      )}
      <p className="small muted">
        Requires local model setup. Video analysis samples up to 30 frames; tags
        and face matches can be wrong. No automatic identity decisions.
      </p>
      <button className="primary" disabled={busy} onClick={() => void action()}>
        Queue local indexing
      </button>{" "}
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void action(true)}
      >
        Forget faces for this file
      </button>
      {message && <p role="status">{message}</p>}
    </section>
  );
}

type Face = {
  id: string;
  media_id: string;
  person_name: string | null;
  model_id: string;
};
function FacePreview({ id, faceId }: { id: string; faceId: string }) {
  const image = useLocalPhoto(id, true, "face", faceId);
  return image.url ? (
    <img
      src={image.url}
      alt="Indexed face to review"
      style={{ width: 160, height: 160, objectFit: "contain" }}
    />
  ) : (
    <span>{image.error || "Loading face…"}</span>
  );
}

export function PeopleBrowser() {
  const { session, preview } = useAuth();
  const cache = useQueryClient();
  const [page, setPage] = useState(0);
  const [group, setGroup] = useState("");
  const groups = useQuery({
    queryKey: ["face-groups", session?.user.id],
    enabled: !!session && !preview,
    queryFn: () =>
      request<{ person_name: string; face_count: number }[]>(
        "/api/v1/face-groups",
        session?.access_token,
      ),
  });
  const [matches, setMatches] = useState<FaceMatch[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState(0.6);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const faces = useQuery({
    queryKey: ["faces", session?.user.id, page, group],
    enabled: !!session && !preview,
    queryFn: () =>
      request<Face[]>(
        `/api/v1/faces?offset=${page * 50}${group ? "&person_name=" + encodeURIComponent(group) : ""}`,
        session?.access_token,
      ),
  });
  async function find(face: Face) {
    setBusy(true);
    setMessage("");
    setMatches([]);
    setSelected([]);
    try {
      const result = await request<{ matches: FaceMatch[] }>(
        `/api/v1/faces/${face.id}/similar?threshold=${threshold}`,
        session?.access_token,
        { method: "POST" },
      );
      setMatches(result.matches);
      setName(face.person_name || "");
      if (!result.matches.length)
        setMessage("No similar faces at this threshold.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    setBusy(true);
    setMessage("");
    try {
      await request("/api/v1/faces/name", session?.access_token, {
        method: "POST",
        body: JSON.stringify({ ids: selected, name }),
      });
      setMatches((rows) =>
        rows.map((row) =>
          selected.includes(row.face_id)
            ? { ...row, person_name: name.trim() || null }
            : row,
        ),
      );
      await cache.invalidateQueries({ queryKey: ["faces"] });
      await cache.invalidateQueries({ queryKey: ["face-groups"] });
      setMessage("Names saved for the faces you selected.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  }
  if (preview)
    return (
      <p>Sign in and opt in to local face indexing to use people search.</p>
    );
  return (
    <section className="panel">
      <h2>Your indexed faces</h2>
      <label>
        People group
        <select
          value={group}
          onChange={(e) => {
            setGroup(e.target.value);
            setPage(0);
            setMatches([]);
            setSelected([]);
          }}
        >
          <option value="">All indexed faces</option>
          {groups.data?.map((g) => (
            <option key={g.person_name} value={g.person_name}>
              {g.person_name} ({g.face_count})
            </option>
          ))}
        </select>
      </label>
      {groups.error && <p role="alert">{groups.error.message}</p>}
      <p>
        Select an indexed face to find similar faces. Review each face crop
        before assigning a name. Matching is a suggestion, not proof of
        identity.
      </p>
      <label>
        Minimum similarity
        <input
          type="number"
          min="0"
          max="1"
          step="0.01"
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
        />
      </label>
      {faces.error && <p role="alert">{faces.error.message}</p>}
      {faces.isPending && <p role="status">Loading faces…</p>}
      {faces.data?.length === 0 && (
        <p>No indexed faces yet. Open a photo and opt in to face indexing.</p>
      )}
      <div className="media-grid">
        {faces.data?.map((face) => (
          <article className="media-card" key={face.id}>
            <FacePreview id={face.media_id} faceId={face.id} />
            <p>{face.person_name || "Unnamed face"}</p>
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void find(face)}
            >
              Find similar faces
            </button>
          </article>
        ))}
      </div>
      <div className="pagination">
        <button disabled={!page} onClick={() => setPage((p) => p - 1)}>
          Previous faces
        </button>
        <button
          disabled={faces.data?.length !== 50}
          onClick={() => setPage((p) => p + 1)}
        >
          Next faces
        </button>
      </div>
      {!!matches.length && (
        <>
          <h3>Review suggested matches</h3>
          <p>No matches are selected automatically.</p>
          <div className="media-grid">
            {matches.map((match) => (
              <article className="media-card" key={match.face_id}>
                <FacePreview id={match.media_id} faceId={match.face_id} />
                <label>
                  <input
                    type="checkbox"
                    checked={selected.includes(match.face_id)}
                    onChange={(e) =>
                      setSelected((ids) =>
                        e.target.checked
                          ? [...ids, match.face_id]
                          : ids.filter((id) => id !== match.face_id),
                      )
                    }
                  />
                  {match.person_name || "Unnamed"} · score{" "}
                  {match.similarity.toFixed(3)}
                </label>
              </article>
            ))}
          </div>
          <label>
            Person name (blank removes name)
            <input
              maxLength={200}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button
            className="primary"
            disabled={busy || !selected.length}
            onClick={() => void save()}
          >
            Save name for selected faces
          </button>
        </>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
