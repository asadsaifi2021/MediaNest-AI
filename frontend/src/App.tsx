import { useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  Link,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bird,
  Grid2X2,
  ScanFace,
  Activity,
  Settings,
  HardDrive,
  ArrowUpRight,
  LogOut,
  Menu,
  X,
  ShieldCheck,
  ArrowRight,
  Sparkles,
  UserRound,
} from "lucide-react";
import { useAuth } from "./auth";
import { AuthScreen } from "./auth-pages";
import { Account } from "./account";
import { request } from "./api";
import { demoOnly } from "./config";
import { ErrorBox } from "./components";
import { Library, Faces, ActivityPage, Connections } from "./pages";

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <Bird size={26} />
      </span>
      <span>
        MediaNest <b>AI</b>
      </span>
    </div>
  );
}
export default function App() {
  const auth = useAuth();
  const [menu, setMenu] = useState(false);
  const location = useLocation();
  const health = useQuery({
    queryKey: ["health"],
    enabled: !demoOnly,
    queryFn: ({ signal }) =>
      request<{ status: string }>("/health", undefined, { signal }),
    refetchInterval: 60000,
  });
  if (auth.loading)
    return (
      <div className="loading-screen" role="status">
        <Bird size={36} />
        <p>Opening your nest…</p>
      </div>
    );
  if (demoOnly && location.pathname.startsWith("/auth/"))
    return <Navigate to="/" replace />;
  if (
    [
      "/auth/callback",
      "/auth/reset-password",
      "/auth/forgot-password",
    ].includes(location.pathname)
  )
    return <AuthScreen key={location.pathname} />;
  if (!auth.session && !auth.preview)
    return <AuthScreen key={location.pathname} />;
  if (location.pathname.startsWith("/auth/"))
    return <Navigate to="/" replace />;
  const nav = [
    { to: "/", icon: Grid2X2, title: "Your library" },
    { to: "/faces", icon: ScanFace, title: "Face search" },
    { to: "/activity", icon: Activity, title: "Activity" },
    { to: "/settings", icon: Settings, title: "Connections" },
    { to: "/account", icon: UserRound, title: "Account" },
  ];
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <Brand />
        <button
          className="mobile-close icon-button"
          aria-label="Close navigation"
          onClick={() => setMenu(false)}
        >
          <X />
        </button>
        <div className="workspace">
          <span className="workspace-avatar">M</span>
          <div>
            <strong>
              {auth.preview ? "The sample nest" : "My private archive"}
            </strong>
            <small>
              {auth.preview ? "Preview workspace" : "Personal workspace"}
            </small>
          </div>
        </div>
        <span className="nav-label">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {nav.map(({ to, icon: Icon, title }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={() => setMenu(false)}
            >
              <Icon size={19} />
              {title}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="storage-note">
            <HardDrive size={23} />
            <strong>At home, by design.</strong>
            <p>
              Your originals belong on your storage. Only their metadata lives
              on the server.
            </p>
            <Link to="/settings" onClick={() => setMenu(false)}>
              View connections <ArrowUpRight size={15} />
            </Link>
          </div>
          <button
            className="account-button"
            disabled={demoOnly}
            onClick={() => {
              setMenu(false);
              if (auth.preview) auth.leavePreview();
              else void auth.signOut();
            }}
          >
            <span className="account-avatar">
              {auth.preview
                ? "P"
                : auth.session?.user.email?.[0]?.toUpperCase() || "M"}
            </span>
            <span>
              <strong>
                {auth.preview
                  ? "Sample preview"
                  : (typeof auth.session?.user.user_metadata.full_name ===
                      "string" &&
                      auth.session.user.user_metadata.full_name) ||
                    auth.session?.user.email}
              </strong>
              <small>
                {demoOnly
                  ? "No account required"
                  : auth.preview
                    ? "Exit preview"
                    : "Sign out"}
              </small>
            </span>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      {menu && (
        <button
          className="nav-scrim"
          aria-label="Dismiss navigation"
          onClick={() => setMenu(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMenu(true)}
            >
              <Menu />
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span>{" "}
              <strong>
                {nav.find((n) => n.to === location.pathname)?.title ||
                  "Your library"}
              </strong>
            </span>
          </div>
          <Link to="/settings" className="connection-pill">
            <i className={health.isSuccess ? "online" : ""} />
            {demoOnly
              ? "Public demo · sample data"
              : health.isPending
                ? "Checking API"
                : health.isSuccess
                  ? "Metadata API online"
                  : "API unavailable"}
          </Link>
        </header>
        {auth.preview && (
          <div className="preview-banner">
            <Sparkles size={15} />
            <span>
              {demoOnly
                ? "Sample demo only. Uploads, playback and live AI processing are disabled. No private storage is connected."
                : "You’re exploring sample content. Your own files haven’t been connected."}
            </span>
            {!demoOnly && (
              <button onClick={auth.leavePreview}>
                Set up my archive <ArrowRight size={14} />
              </button>
            )}
          </div>
        )}
        <main id="main" tabIndex={-1}>
          {auth.error && <ErrorBox error={auth.error} />}
          <Routes>
            <Route
              path="/"
              element={<Library key={auth.session?.user.id || "sample"} />}
            />
            <Route
              path="/faces"
              element={<Faces key={auth.session?.user.id || "sample"} />}
            />
            <Route path="/activity" element={<ActivityPage />} />
            <Route
              path="/settings"
              element={
                demoOnly ? (
                  <section className="panel">
                    <h1>About this demonstration</h1>
                    <p>
                      Explore the sample library, search, filters and media
                      details. All content here is fictional sample data.
                    </p>
                    <p>
                      This public website has no connection to a database or
                      home storage. Uploads, playback, account changes and AI
                      processing require a separately configured private
                      installation.
                    </p>
                    <Link to="/">Explore the sample library</Link>
                  </section>
                ) : (
                  <Connections />
                )
              }
            />
            <Route
              path="/account"
              element={<Account key={auth.session?.user.id || "sample"} />}
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
        <footer>
          <span>Made for the moments worth keeping.</span>
          <span>
            <ShieldCheck size={14} /> Private by design
          </span>
        </footer>
      </div>
    </div>
  );
}
