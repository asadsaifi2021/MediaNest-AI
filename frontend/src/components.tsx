import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Image,
  Film,
  AudioLines,
  X,
  HardDrive,
  AlertCircle,
  Search,
} from "lucide-react";
import type { Media } from "./types";
import { OriginalPhoto, useLocalPhoto } from "./photos";

export const typeIcons = { image: Image, video: Film, audio: AudioLines };
export const typeNames = { image: "Photo", video: "Video", audio: "Audio" };
export function filename(value: string) {
  return value.split(/[\\/]/).pop() || value;
}
export function date(value: string) {
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
export function ErrorBox({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>Something needs attention</strong>
        <p>{error instanceof Error ? error.message : String(error)}</p>
        {retry && (
          <button className="text-button" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Search size={30} />
      </span>
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby="dialog-title"
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="dialog-heading">
        <h2 id="dialog-title">{title}</h2>
        <button
          className="icon-button"
          aria-label="Close details"
          onClick={onClose}
        >
          <X />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Thumbnail({ media }: { media: Media }) {
  const [failed, setFailed] = useState(false);
  const local = useLocalPhoto(media.id, Boolean(media.original_filename));
  const Icon = typeIcons[media.file_type] ?? Image;
  let url: string | null = null;
  try {
    const parsed = new URL(media.thumbnail_url || "", window.location.origin);
    if (media.thumbnail_url && ["http:", "https:"].includes(parsed.protocol))
      url = parsed.href;
  } catch {
    /* Unsupported references are shown as unavailable. */
  }
  if (media.original_filename) url = local.url || null;
  return (
    <div className={`thumbnail ${media.file_type}`}>
      {url && !failed ? (
        <img
          src={url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="thumbnail-fallback">
          <Icon size={36} />
          <span>
            {local.error
              ? "Local storage unavailable"
              : failed
                ? "Preview unavailable"
                : media.original_filename
                  ? "Loading local preview…"
                  : "No preview yet"}
          </span>
        </div>
      )}
      <span className="media-kind">
        <Icon size={13} />
        {typeNames[media.file_type]}
      </span>
    </div>
  );
}
export function MediaDetails({
  media,
  onClose,
  preview,
}: {
  media: Media;
  onClose: () => void;
  preview: boolean;
}) {
  return (
    <Modal
      title={filename(media.original_filename || media.local_file_id)}
      onClose={onClose}
    >
      <Thumbnail media={media} />
      <div className="dialog-body">
        <div className="tags">
          {media.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <dl>
          <dt>Media type</dt>
          <dd>{typeNames[media.file_type]}</dd>
          <dt>Added</dt>
          <dd>{date(media.created_at)}</dd>
          <dt>Storage node</dt>
          <dd>{media.device_id}</dd>
          <dt>File reference</dt>
          <dd>{media.local_file_id}</dd>
        </dl>
        {media.transcription && (
          <section>
            <h3>Transcript</h3>
            <p className="transcript">{media.transcription}</p>
          </section>
        )}
        <div className="notice">
          <HardDrive size={20} />
          <p>
            {preview
              ? "This is an illustrated sample, not a stored file."
              : media.original_filename
                ? "This photo is stored on your PC, not in Supabase."
                : "This legacy record contains metadata only; its local file is not connected."}
          </p>
        </div>
        {!preview && media.original_filename && <OriginalPhoto id={media.id} />}
      </div>
    </Modal>
  );
}
