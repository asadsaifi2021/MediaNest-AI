import { useEffect, useState } from "react";
type InstallEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: string }>;
};
export function InstallApp() {
  const [prompt, setPrompt] = useState<InstallEvent | null>(null);
  useEffect(() => {
    const handler = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallEvent);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);
  return (
    <section className="panel">
      <h2>Install MediaNest</h2>
      <p>
        On your private HTTPS address, use Chrome’s Install app menu on Android,
        or Edge’s Apps → Install on Windows. Keep Tailscale connected and your
        storage PC awake.
      </p>
      {prompt && (
        <button
          className="primary"
          onClick={() =>
            void (async () => {
              await prompt.prompt();
              await prompt.userChoice;
              setPrompt(null);
            })()
          }
        >
          Install MediaNest
        </button>
      )}
      <p className="small muted">
        Installation does not enable background phone backup. Private metadata
        and media are not cached offline.
      </p>
    </section>
  );
}
