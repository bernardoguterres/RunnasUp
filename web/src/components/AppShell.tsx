import { useRef, useEffect, useId, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { useAppState } from "../state/AppState";
import { KindTag, RunnerOptions } from "./Badges";

type NavItem = { to: string; label: string; end?: boolean; icon: IconName; tag?: string };

const PRIMARY: NavItem[] = [
  { to: "/", label: "Overview", end: true, icon: "chart" },
  { to: "/activities", label: "Activities", icon: "list" },
  { to: "/mmr/compare", label: "Compare", icon: "bars" },
  { to: "/import", label: "Import history", icon: "upload" },
];
const EXPLORE: NavItem[] = [{ to: "/lab", label: "Ratings Lab", icon: "flask", tag: "Experimental" }];
type IconName = "chart" | "list" | "bars" | "upload" | "flask" | "help" | "db" | "chev";
const PATHS: Record<IconName, string> = {
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  bars: "M6 20V14M12 20V8M18 20V11",
  upload: "M12 15V3m0 0-4 4m4-4 4 4M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4",
  flask: "M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3",
  help: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01",
  db: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  chev: "m9 6 6 6-6 6",
};

export function Icon({ name, className }: { name: IconName; className?: string }) {
  return (
    <svg className={className ?? "icon"} viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"
      fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  );
}

/** Wordmark: a stylised stride mark + the name. */
export function Logo() {
  return (
    <span className="logo">
      <svg className="logo__mark" viewBox="0 0 32 32" width="28" height="28" aria-hidden="true" focusable="false">
        <path d="M5 24 15 8M12 26 22 10M19 26l8-13" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" />
      </svg>
      <span className="logo__text">
        Runnas<span className="logo__up">UP</span>
      </span>
    </span>
  );
}

function NavList({ items, label }: { items: NavItem[]; label?: string }) {
  return (
    <ul className="side-nav__list" aria-label={label}>
      {items.map((n) => (
        <li key={n.to}>
          <NavLink to={n.to} end={n.end} className="side-nav__link">
            <Icon name={n.icon} />
            <span>{n.label}</span>
            {n.tag ? <>{" "}<span className="tag tag--exp">{n.tag}</span></> : null}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

const DB_LABEL = { personal: "Personal database", demo: "Demo database", custom: "Custom database" } as const;

export function ParticipantSelect() {
  const { participants, participantId, setParticipantId, participantsLoading } = useAppState();
  const id = useId();
  const current = participants?.find((p) => p.id === participantId) ?? null;
  if (!participants || participants.length === 0) {
    return (
      <div className="topbar__field">
        <span className="field__label">Runner</span>
        <span className="muted">{participantsLoading ? "Loading…" : "No runners yet"}</span>
      </div>
    );
  }
  return (
    <div className="topbar__field">
      <label htmlFor={id} className="field__label">
        Runner
      </label>
      <div className="topbar__select-row">
        <select
          id={id}
          value={participantId ?? ""}
          onChange={(e) => setParticipantId(Number(e.target.value))}
        >
          <RunnerOptions participants={participants} />
        </select>
        {current ? <KindTag kind={current.data_kind} /> : null}
      </div>
    </div>
  );
}

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Overview"],
  [/^\/mmr\/compare/, "Compare Running MMR"],
  [/^\/mmr\/explain/, "Explain an MMR change"],
  [/^\/activities\/.+/, "Activity"],
  [/^\/activities/, "Activities"],
  [/^\/import/, "Import activities"],
  [/^\/method/, "How Running MMR works"],
  [/^\/lab/, "Ratings Lab (experimental)"],
];

export function pageTitle(pathname: string): string {
  return TITLES.find(([re]) => re.test(pathname))?.[1] ?? "Not found";
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  const navId = useId();
  const { health } = useAppState();

  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  // announce navigation: page title for the tab and screen readers, focus moved to the new content
  const firstRender = useRef(true);
  useEffect(() => {
    document.title = `${pageTitle(location.pathname)} · RunnasUP`;
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    document.getElementById("main")?.focus();
  }, [location.pathname]);

  const db = health ? DB_LABEL[health.database] : null;
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar${menuOpen ? " sidebar--open" : ""}`}>
        <NavLink to="/" className="sidebar__brand" end aria-label="RunnasUP home">
          <Logo />
        </NavLink>
        <nav id={navId} className="side-nav" aria-label="Main">
          <p className="side-nav__heading">Personal</p>
          <NavList items={PRIMARY} />
          <p className="side-nav__heading">Explore</p>
          <NavList items={EXPLORE} />
          <div className="side-nav__bottom">
            <NavList items={[{ to: "/method", label: "How Running MMR works", icon: "help" }]} />
          </div>
        </nav>
        <div className="sidebar__workspace">
          <Icon name="db" />
          <span>
            <span className="muted small">Local workspace</span>
            <br />
            <span className="small">{db ?? "Connecting…"}</span>
          </span>
        </div>
      </aside>
      {menuOpen ? <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" /> : null}
      <div className="app__main">
        <header className="topbar">
          <button type="button" className="btn menu-btn" aria-expanded={menuOpen} aria-controls={navId}
            onClick={() => setMenuOpen((o) => !o)}>
            Menu
          </button>
          <nav className="crumbs" aria-label="Breadcrumb">
            <span className={`crumbs__db${health && health.database !== "personal" ? " crumbs__db--synthetic" : ""}`}
              title={health ? `Database: ${health.database}` : undefined}>
              {db ?? "…"}
            </span>
            <span aria-hidden="true" className="crumbs__sep">/</span>
            <span aria-current="page">{pageTitle(location.pathname)}</span>
          </nav>
          <div className="topbar__controls">
            <ParticipantSelect />
          </div>
        </header>
        <main id="main" className="main" tabIndex={-1}>
          <Outlet />
        </main>
        <footer className="footer">
          RunnasUP runs locally on this computer. Running MMR is a personal estimate from your own activities, not a
          percentile, and not validated.
        </footer>
      </div>
    </div>
  );
}
