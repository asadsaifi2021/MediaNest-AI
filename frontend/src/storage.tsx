import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { useAuth } from "./auth";
import { request } from "./api";
import { ErrorBox } from "./components";

interface StorageNode {
  id: string;
  device_id: string;
  display_name: string;
  base_url: string;
  created_at: string;
  disabled_at: string | null;
}

export function StorageRegistry() {
  const { session, preview } = useAuth();
  const cache = useQueryClient();
  const [name, setName] = useState("This Windows PC");
  const [device, setDevice] = useState("windows-pc");
  const [origin, setOrigin] = useState("http://127.0.0.1:8100");
  const [notice, setNotice] = useState("");
  const [offset, setOffset] = useState(0);
  const key = ["storage-nodes", session?.user.id];
  const nodes = useQuery({
    queryKey: [...key, offset],
    enabled: Boolean(session && !preview),
    queryFn: ({ signal }) =>
      request<StorageNode[]>(
        `/api/v1/storage-nodes?limit=20&offset=${offset}`,
        session?.access_token,
        { signal },
      ),
  });
  const register = useMutation({
    mutationFn: () =>
      request<StorageNode>("/api/v1/storage-nodes", session?.access_token, {
        method: "POST",
        body: JSON.stringify({
          display_name: name.trim(),
          device_id: device,
          base_url: origin,
        }),
      }),
    onSuccess: async () => {
      setNotice(
        "Storage registered. Connectivity is not verified; configure the local service before uploading.",
      );
      setOffset(0);
      await cache.invalidateQueries({ queryKey: key });
    },
  });
  const disable = useMutation({
    mutationFn: (id: string) =>
      request<StorageNode>(
        `/api/v1/storage-nodes/${id}/disable`,
        session?.access_token,
        { method: "POST" },
      ),
    onSuccess: async () => {
      setNotice("Registration disabled. No files were deleted.");
      await cache.invalidateQueries({ queryKey: key });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    setNotice("");
    register.mutate();
  }
  return (
    <section className="panel" aria-labelledby="storage-heading">
      <span className="eyebrow">FIRST STORAGE STEP</span>
      <h2 id="storage-heading">Register your local storage</h2>
      <p className="muted">
        Save a name and server address for your PC or NAS. This registers
        metadata only: it does not create a folder, contact that address, or
        enable file uploads.
      </p>
      {preview ? (
        <p>
          Sign in to register your own storage. Sample mode does not save
          changes.
        </p>
      ) : (
        <>
          <form onSubmit={submit}>
            <label>
              Storage name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                maxLength={100}
              />
            </label>
            <label>
              Device ID
              <input
                value={device}
                onChange={(e) => setDevice(e.target.value)}
                required
                pattern="[a-zA-Z0-9_-]{1,128}"
                maxLength={128}
              />
            </label>
            <p className="small muted">
              Use letters, numbers, hyphens, or underscores. Each device ID is
              unique in your account.
            </p>
            <label>
              Storage server address
              <input
                type="url"
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                required
                maxLength={2048}
              />
            </label>
            <p className="small muted">
              For this PC, keep http://127.0.0.1:8100. Other devices will need
              the PC's private HTTPS address later. Do not enter a folder path
              or password.
            </p>
            <button
              className="primary"
              disabled={register.isPending || !session || !name.trim()}
            >
              {register.isPending ? "Registering…" : "Register storage"}
            </button>
          </form>
          {register.error && <ErrorBox error={register.error} />}
          {disable.error && <ErrorBox error={disable.error} />}
          {notice && <p role="status">{notice}</p>}
          <h3>Your registered storage</h3>
          {nodes.isPending ? (
            <p role="status">Loading storage…</p>
          ) : nodes.isError ? (
            <ErrorBox error={nodes.error} retry={() => void nodes.refetch()} />
          ) : !nodes.data?.length ? (
            <p>No storage registrations on this page.</p>
          ) : (
            <ul className="storage-list">
              {nodes.data.map((node) => (
                <li key={node.id}>
                  <div>
                    <strong>{node.display_name}</strong>
                    <p>
                      {node.device_id} · {node.base_url}
                    </p>
                    <span className="small">
                      {node.disabled_at
                        ? "Disabled"
                        : "Registered · connectivity not verified"}
                    </span>
                  </div>
                  {!node.disabled_at && (
                    <button
                      className="secondary"
                      disabled={disable.isPending}
                      onClick={() => {
                        if (
                          window.confirm(
                            "Disable this storage registration? This will not delete any files.",
                          )
                        ) {
                          setNotice("");
                          disable.mutate(node.id);
                        }
                      }}
                    >
                      Disable {node.display_name}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="pagination">
            <button
              className="secondary"
              disabled={offset === 0 || nodes.isFetching}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              Previous storage
            </button>
            <button
              className="secondary"
              disabled={nodes.data?.length !== 20 || nodes.isFetching}
              onClick={() => setOffset(offset + 20)}
            >
              Next storage
            </button>
          </div>
        </>
      )}
    </section>
  );
}
