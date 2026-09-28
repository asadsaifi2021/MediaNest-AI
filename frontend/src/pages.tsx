import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams, Link } from "react-router-dom";
import {
  Search,
  SlidersHorizontal,
  Grid2X2,
  List,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  HardDrive,
  Image,
  Film,
  AudioLines,
  Plus,
  Server,
  KeyRound,
  CheckCircle2,
  Clock,
  ScanFace,
  RefreshCw,
} from "lucide-react";
import { useAuth } from "./auth";
import { configIssue } from "./config";
import { request, parseEmbedding } from "./api";
import { sampleMedia } from "./demo";
import { StorageRegistry } from "./storage";
import { PhotoUpload } from "./photos";
import type { ArchiveEvent, FaceMatch, Media, MediaPage } from "./types";
import {
  date,
  Empty,
  ErrorBox,
  filename,
  MediaDetails,
  Modal,
  Thumbnail,
} from "./components";

export function Library() {
  const { session, preview } = useAuth();
  const [params, setParams] = useSearchParams();
  const tag = params.get("tag") || "";
  const rawType = params.get("type") || "";
  const type = ["image", "video", "audio"].includes(rawType) ? rawType : "";
  const sort = params.get("sort") === "oldest" ? "oldest" : "newest";
  const page = Math.min(
    100000,
    Math.max(0, Number.parseInt(params.get("page") || "0") || 0),
  );
  const [search, setSearch] = useState(tag);
  useEffect(() => setSearch(tag), [tag]);
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [selected, setSelected] = useState<Media | null>(null);
  const [importInfo, setImportInfo] = useState(false);
  function update(values: Record<string, string>) {
    const next = new URLSearchParams(params);
    next.delete("page");
    for (const [key, value] of Object.entries(values))
      value ? next.set(key, value) : next.delete(key);
    setParams(next);
  }
  const query = useQuery({
    queryKey: ["media", session?.user.id, preview, tag, type, sort, page],
    enabled: preview || Boolean(session),
    queryFn: ({ signal }): Promise<MediaPage> => {
      if (preview) {
        const matches = sampleMedia.filter(
          (m) =>
            (!type || m.file_type === type) && (!tag || m.tags.includes(tag)),
        );
        if (sort === "oldest") matches.reverse();
        return Promise.resolve({
          results: matches.slice(page * 24, (page + 1) * 24),
          has_more: matches.length > (page + 1) * 24,
        });
      }
      const filters = new URLSearchParams({
        limit: "24",
        offset: String(page * 24),
        sort,
      });
      if (type) filters.set("file_type", type);
      if (tag) filters.set("tag", tag);
      return request<MediaPage>(
        "/api/v1/media?" + filters,
        session?.access_token,
        { signal },
      );
    },
  });
  const items = query.data?.results || [];
  const kinds: { key: string; text: string; icon: typeof Image }[] = [
    { key: "", text: "All media", icon: Grid2X2 },
    { key: "image", text: "Photos", icon: Image },
    { key: "video", text: "Videos", icon: Film },
    { key: "audio", text: "Audio", icon: AudioLines },
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR PERSONAL ARCHIVE</span>
          <h1>
            A home for your moments<span>.</span>
          </h1>
          <p>Photos, films, and familiar voices. All together, all yours.</p>
        </div>
        <button className="primary" onClick={() => setImportInfo(true)}>
          <Plus size={18} />
          Add media
        </button>
      </div>
      <section className="library-intro">
        <div>
          <span className="intro-badge">
            <HardDrive size={14} />
            LOCAL FILES · SERVER METADATA
          </span>
          <h2>
            Keep it close.
            <br />
            Find it effortlessly.
          </h2>
          <p>
            Your archive stays on your storage.
            <br />
            Search brings the memories to you.
          </p>
          <Link to="/settings">
            See how your archive connects <ArrowUpRight size={16} />
          </Link>
        </div>
        <div className="intro-art" aria-hidden="true">
          <div className="art-card back">
            <img src="/samples/garden.svg" alt="" />
          </div>
          <div className="art-card front">
            <img src="/samples/lake.svg" alt="" />
            <span>A moment worth keeping</span>
          </div>
          <span className="art-label">
            <CheckCircle2 size={15} /> Yours to keep
          </span>
        </div>
      </section>
      <section className="library-section" aria-label="Media library">
        <div className="section-title">
          <h2>
            {tag ? `Tagged “${tag}”` : "Your library"}{" "}
            <span>{preview ? "SAMPLE" : "PRIVATE"}</span>
          </h2>
          <div className="view-toggle" aria-label="View layout">
            <button
              aria-label="Grid view"
              aria-pressed={layout === "grid"}
              onClick={() => setLayout("grid")}
            >
              <Grid2X2 size={17} />
            </button>
            <button
              aria-label="List view"
              aria-pressed={layout === "list"}
              onClick={() => setLayout("list")}
            >
              <List size={18} />
            </button>
          </div>
        </div>
        <div className="library-controls">
          <div className="type-tabs">
            {kinds.map(({ key, text, icon: Icon }) => (
              <button
                key={key}
                aria-pressed={type === key}
                className={type === key ? "selected" : ""}
                onClick={() => update({ type: key })}
              >
                <Icon size={16} />
                {text}
              </button>
            ))}
          </div>
          <form
            className="search-form"
            onSubmit={(e) => {
              e.preventDefault();
              update({ tag: search.trim() });
            }}
          >
            <Search size={18} />
            <input
              aria-label="Search by exact tag"
              placeholder="Search an exact tag…"
              maxLength={100}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button aria-label="Submit tag search">
              <ArrowUpRight size={17} />
            </button>
          </form>
          <label className="sort-control">
            <SlidersHorizontal size={16} />
            <select
              aria-label="Sort media"
              value={sort}
              onChange={(e) => update({ sort: e.target.value })}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </select>
          </label>
        </div>
        <div className="result-info">
          <span>
            {query.isPending
              ? "Opening library…"
              : `${items.length} item${items.length === 1 ? "" : "s"} on this page`}
            {preview ? " · Illustrated sample collection" : ""}
          </span>
          {tag && (
            <button
              className="text-button"
              onClick={() => {
                setSearch("");
                update({ tag: "" });
              }}
            >
              Clear search
            </button>
          )}
        </div>
        {query.isError ? (
          <ErrorBox error={query.error} retry={() => void query.refetch()} />
        ) : query.isPending ? (
          <div
            className="media-grid"
            aria-label="Loading library"
            role="status"
          >
            {[1, 2, 3].map((i) => (
              <div className="skeleton" key={i} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <Empty
            title={
              tag || type ? "No matching moments yet" : "Your story starts here"
            }
          >
            {tag || type
              ? "Try another exact tag or choose All media. Tags are case-sensitive."
              : "Connect your local storage and sync metadata to fill your library."}
          </Empty>
        ) : (
          <div
            className={`media-grid ${layout === "list" ? "list-layout" : ""}`}
          >
            {items.map((media) => (
              <article className="media-card" key={media.id}>
                <button
                  className="media-open"
                  onClick={() => setSelected(media)}
                  aria-label={`Open ${filename(media.original_filename || media.local_file_id)}`}
                >
                  <Thumbnail media={media} />
                  <div className="card-copy">
                    <h3>
                      {filename(media.original_filename || media.local_file_id)}
                    </h3>
                    <p>
                      {date(media.created_at)}
                      <span>
                        {" "}
                        · {preview ? "Sample media" : media.device_id}
                      </span>
                    </p>
                  </div>
                </button>
                <div className="tags">
                  {media.tags.slice(0, 3).map((t) => (
                    <button
                      key={t}
                      onClick={() => {
                        setSearch(t);
                        update({ tag: t });
                      }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}
        <div className="pagination">
          <button
            className="secondary"
            disabled={page === 0 || query.isFetching}
            onClick={() => update({ page: String(page - 1) })}
          >
            <ChevronLeft size={16} />
            Previous
          </button>
          <span>Page {page + 1}</span>
          <button
            className="secondary"
            disabled={!query.data?.has_more || query.isFetching}
            onClick={() => update({ page: String(page + 1) })}
          >
            Next
            <ChevronRight size={16} />
          </button>
        </div>
      </section>
      {selected && (
        <MediaDetails
          media={selected}
          preview={preview}
          onClose={() => setSelected(null)}
        />
      )}
      {importInfo && (
        <Modal
          title="A place for your originals"
          onClose={() => setImportInfo(false)}
        >
          <div className="dialog-body">
            <PhotoUpload done={() => setImportInfo(false)} />
            {preview && (
              <>
                <div className="empty-icon">
                  <HardDrive size={32} />
                </div>
                <p>
                  Uploads will go directly to your home storage. The local
                  storage service and its upload authorization are the next
                  implementation stage.
                </p>
                <p>
                  No file will be selected or uploaded yet. You can browse
                  sample media or connect Supabase to view metadata already
                  indexed by your server.
                </p>
                <Link
                  className="primary"
                  to="/settings"
                  onClick={() => setImportInfo(false)}
                >
                  View connections <ArrowUpRight size={17} />
                </Link>
              </>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}

export function Faces() {
  const { preview, session } = useAuth();
  const [text, setText] = useState("");
  const [threshold, setThreshold] = useState("0.6");
  const [submitted, setSubmitted] = useState<{
    embedding: number[];
    threshold: number;
    nonce: number;
  } | null>(null);
  const [error, setError] = useState("");
  const [mediaId, setMediaId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["face-search", session?.user.id, submitted],
    enabled: Boolean(session && submitted && !preview),
    queryFn: ({ signal }) =>
      request<{ matches: FaceMatch[] }>(
        "/api/v1/media/search-face",
        session?.access_token,
        {
          method: "POST",
          body: JSON.stringify({
            embedding: submitted!.embedding,
            threshold: submitted!.threshold,
            limit: 20,
          }),
          signal,
        },
      ),
  });
  const details = useQuery({
    queryKey: ["media-detail", session?.user.id, mediaId],
    enabled: Boolean(mediaId && session),
    queryFn: ({ signal }) =>
      request<Media>(`/api/v1/media/${mediaId}`, session?.access_token, {
        signal,
      }),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setMediaId(null);
    try {
      setSubmitted({
        embedding: parseEmbedding(text),
        threshold: Number(threshold),
        nonce: Date.now(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid vector.");
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">FIND A FAMILIAR FACE</span>
          <h1>
            People make the memories<span>.</span>
          </h1>
          <p>Search indexed faces within your own archive.</p>
        </div>
        <ScanFace size={34} />
      </div>
      <div className="panel">
        <h2>Face search connection</h2>
        <p className="muted">
          Photo-based face search needs the local AI worker. Until that is
          connected, you can test the existing API using a 512-value embedding
          from the same model used to index your archive.
        </p>
        <div className="notice">
          <HardDrive size={20} />
          <p>
            Photo upload and face extraction are not available yet. Embeddings
            from different models cannot be compared reliably.
          </p>
        </div>
        <form onSubmit={submit}>
          <label>
            Face embedding (JSON)
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="[0.012, -0.034, …]"
              rows={6}
              required
              disabled={preview}
            />
          </label>
          <label>
            Similarity threshold
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              required
              disabled={preview}
            />
          </label>
          {error && <ErrorBox error={error} />}
          <button className="primary" disabled={preview || query.isFetching}>
            <Search size={17} />
            {query.isFetching ? "Searching…" : "Search faces"}
          </button>
        </form>
        {preview && (
          <p className="small muted">
            Sign in to search real face metadata. This preview does not simulate
            recognition.
          </p>
        )}
      </div>
      {query.error && <ErrorBox error={query.error} />}
      {query.data && (
        <div className="panel">
          <h2>{query.data.matches.length} face matches</h2>
          {!query.data.matches.length && <p>No faces met that threshold.</p>}
          {query.data.matches.map((match) => (
            <button
              className="match-row"
              key={match.face_id}
              onClick={() => setMediaId(match.media_id)}
            >
              <span>
                <strong>{match.person_name || "Unnamed person"}</strong>
                <small>{match.media_id}</small>
              </span>
              <span>
                {match.similarity.toFixed(3)} similarity{" "}
                <ArrowUpRight size={15} />
              </span>
            </button>
          ))}
          <p className="small muted">
            Similarity is a model score, not a probability of identity. Confirm
            matches yourself.
          </p>
        </div>
      )}
      {details.isFetching && mediaId && (
        <p role="status">Loading media details…</p>
      )}
      {details.error && (
        <ErrorBox error={details.error} retry={() => void details.refetch()} />
      )}
      {details.data && mediaId && (
        <MediaDetails
          media={details.data}
          preview={false}
          onClose={() => setMediaId(null)}
        />
      )}
    </>
  );
}

export function ActivityPage() {
  const { session, preview } = useAuth();
  const query = useQuery({
    queryKey: ["activity", session?.user.id],
    enabled: Boolean(session && !preview),
    queryFn: ({ signal }) =>
      request<ArchiveEvent[]>(
        "/api/v1/archive-events?limit=50",
        session?.access_token,
        { signal },
      ),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">BEHIND THE MOMENTS</span>
          <h1>
            Your archive, in motion<span>.</span>
          </h1>
          <p>The latest 50 lifecycle events reported by your devices.</p>
        </div>
        <button
          className="secondary"
          disabled={preview || query.isFetching}
          onClick={() => void query.refetch()}
        >
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
      {preview ? (
        <Empty title="Real activity will appear here">
          The sample library does not create server events. Connect your archive
          to see synchronization history.
        </Empty>
      ) : query.isPending ? (
        <p role="status">Loading activity…</p>
      ) : query.isError ? (
        <ErrorBox error={query.error} retry={() => void query.refetch()} />
      ) : !query.data?.length ? (
        <Empty title="A quiet nest">
          No archive events have been reported yet.
        </Empty>
      ) : (
        <div className="panel">
          {query.data.map((event) => (
            <div className="activity-row" key={event.id}>
              <Clock size={19} />
              <div>
                <strong>{event.event_type}</strong>
                <p>
                  {event.device_id} · {event.asset_id}
                </p>
              </div>
              <time>{date(event.occurred_at)}</time>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ConnectionRow({
  title,
  description,
  state,
  icon: Icon,
}: {
  title: string;
  description: string;
  state: string;
  icon: typeof Server;
}) {
  return (
    <div className="connection-row">
      <span className="connection-icon">
        <Icon size={22} />
      </span>
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <span
        className={`state ${state === "Connected" || state === "Configured" ? "good" : ""}`}
      >
        {state}
      </span>
    </div>
  );
}
export function Connections() {
  const api = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) =>
      request<{ status: string }>("/health", undefined, { signal }),
  });
  const db = useQuery({
    queryKey: ["db-health"],
    queryFn: ({ signal }) =>
      request<{ status: string }>("/db-health", undefined, { signal }),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <span className="eyebrow">EVERYTHING IN ITS PLACE</span>
          <h1>
            Your archive connections<span>.</span>
          </h1>
          <p>Metadata on the server. Your files at home.</p>
        </div>
        <button
          className="secondary"
          disabled={api.isFetching || db.isFetching}
          onClick={() => {
            void api.refetch();
            void db.refetch();
          }}
        >
          <RefreshCw size={16} />
          Check again
        </button>
      </div>
      <div className="panel connection-panel">
        <ConnectionRow
          icon={Server}
          title="Metadata API"
          description={
            api.error?.message ||
            "The FastAPI service that powers your library and search."
          }
          state={
            api.isPending
              ? "Checking"
              : api.isSuccess
                ? "Connected"
                : "Unavailable"
          }
        />
        <ConnectionRow
          icon={KeyRound}
          title="Supabase authentication"
          description={
            configIssue ||
            "Public browser configuration is present. Sign in to verify your account."
          }
          state={configIssue ? "Needs setup" : "Configured"}
        />
        <ConnectionRow
          icon={Grid2X2}
          title="Metadata database"
          description={
            db.error?.message ||
            "Supabase stores tags, transcripts, and search vectors."
          }
          state={
            db.isPending
              ? "Checking"
              : db.isSuccess
                ? "Connected"
                : "Needs setup"
          }
        />
        <ConnectionRow
          icon={HardDrive}
          title="Local media storage"
          description="Register your PC or NAS below. Secure enrollment, uploads, and playback are still upcoming."
          state="Setup required"
        />
      </div>
      <StorageRegistry />
      <div className="two-panels">
        <section className="panel">
          <span className="eyebrow">CONNECT YOUR ACCOUNT</span>
          <h2>One small setup step.</h2>
          <ol className="setup-list">
            <li>
              Copy <code>frontend/.env.example</code> to{" "}
              <code>frontend/.env.local</code>.
            </li>
            <li>
              Set your Supabase project URL and its <strong>publishable</strong>{" "}
              key.
            </li>
            <li>
              Configure the backend’s separate server environment and run the
              SQL migrations.
            </li>
            <li>
              Restart the frontend and backend, then sign in with an existing
              account.
            </li>
          </ol>
          <p className="small muted">
            Never use a secret or service-role key in frontend configuration.
          </p>
        </section>
        <section className="panel privacy-panel">
          <HardDrive size={30} />
          <h2>Local means yours.</h2>
          <p>
            Originals, thumbnails, and playback copies belong on your NAS. The
            server holds references and searchable metadata.
          </p>
          <p>
            If your storage is offline, search can still find records, but
            previews and playback may be unavailable.
          </p>
        </section>
      </div>
    </>
  );
}
