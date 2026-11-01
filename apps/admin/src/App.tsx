// dotrix admin: the console for whoever operates dotrix. It has its own accounts and sign-in
// (/v1/admin/*, never the web app's session) and reads the whole platform's health and use, across
// every workspace, without what people wrote.
import {
  ArrowUpRightIcon,
  ChartBarIcon,
  CodeIcon,
  EyeIcon,
  EyeSlashIcon,
  ListBulletsIcon,
  LockKeyIcon,
  ScrollIcon,
  SignOutIcon,
  SquaresFourIcon,
  WarningCircleIcon,
  WarningOctagonIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";

import { call, rawCall, refreshSession, type Me } from "./api";

// The pages (and their charts and tables) load after sign-in, so the sign-in page is small and quick.
const pages = () => import("./pages");
const Overview = lazy(() => pages().then((m) => ({ default: m.Overview })));
const Runs = lazy(() => pages().then((m) => ({ default: m.Runs })));
const FailuresPage = lazy(() => pages().then((m) => ({ default: m.FailuresPage })));
const CodingPage = lazy(() => pages().then((m) => ({ default: m.CodingPage })));
const WorkspacesPage = lazy(() => pages().then((m) => ({ default: m.WorkspacesPage })));
const AuditPage = lazy(() => pages().then((m) => ({ default: m.AuditPage })));

/** Where people who use dotrix sign in: the web app (`VITE_APP_URL`, set at build time). */
const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined) ?? "https://app.dotrix.cc";

const PAGES: { id: string; label: string; icon: Icon }[] = [
  { id: "overview", label: "Overview", icon: ChartBarIcon },
  { id: "runs", label: "Runs", icon: ListBulletsIcon },
  { id: "failures", label: "Failures", icon: WarningOctagonIcon },
  { id: "coding", label: "Coding", icon: CodeIcon },
  { id: "workspaces", label: "Workspaces", icon: SquaresFourIcon },
  { id: "audit", label: "Audit log", icon: ScrollIcon },
];

function Mark({ size = 20 }: { size?: number }) {
  const dots = [3, 10, 17].flatMap((y) => [3, 10, 17].map((x) => [x, y] as const));
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" aria-hidden="true">
      {dots.map(([x, y]) => (
        <circle key={`${x}${y}`} cx={x} cy={y} r={x === 10 && y === 10 ? 3.2 : 1.7} fill="var(--brand)" opacity={x === 10 && y === 10 ? 1 : 0.62} />
      ))}
    </svg>
  );
}

function usePage(): [string, (p: string) => void] {
  const read = () => {
    const id = location.hash.replace(/^#\/?/, "");
    return PAGES.some((p) => p.id === id) ? id : "overview";
  };
  const [page, setPage] = useState(read);
  useEffect(() => {
    const on = () => setPage(read());
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return [page, (p: string) => (location.hash = `/${p}`)];
}

function Login({ onAuth }: { onAuth: () => void }) {
  const boot = useQuery({ queryKey: ["bootstrap"], queryFn: () => rawCall<{ enabled: boolean }>("/admin/bootstrap"), staleTime: 60_000 });
  const first = boot.data?.enabled === true;
  const [f, setF] = useState({ email: "", name: "", password: "" });
  const [show, setShow] = useState(false);
  const auth = useMutation({
    mutationFn: () =>
      rawCall<void>(first ? "/admin/signup" : "/admin/login", {
        method: "POST",
        body: first ? f : { email: f.email, password: f.password },
      }),
    onSuccess: onAuth,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    auth.mutate();
  };
  return (
    <main className="ad-auth">
      <div className="ad-auth-bg" aria-hidden="true" />
      <form className="ad-auth-card" onSubmit={submit} aria-busy={auth.isPending}>
        <span className="ad-auth-brand">
          <Mark size={22} />
          dotrix <em>admin</em>
        </span>
        <div>
          <h1>{first ? "Create the first admin account" : "Sign in to the console"}</h1>
          <p className="ad-auth-sub">
            {first
              ? "This form is open only until the first account exists. The account is separate from any dotrix app account."
              : "For whoever operates dotrix. A dotrix app account doesn't sign in here."}
          </p>
        </div>
        {auth.isError && (
          <p className="ad-auth-error" role="alert">
            <WarningCircleIcon size={16} weight="fill" />
            {auth.error.message}
          </p>
        )}
        {first && (
          <label>
            Name
            <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required autoComplete="name" autoFocus />
          </label>
        )}
        <label>
          Email
          <input
            className="input"
            type="email"
            value={f.email}
            onChange={(e) => setF({ ...f, email: e.target.value })}
            required
            autoComplete="username"
            autoFocus={!first}
          />
        </label>
        <label>
          {first ? "Password (at least 8 characters)" : "Password"}
          <span className="ad-pw">
            <input
              className="input"
              type={show ? "text" : "password"}
              value={f.password}
              onChange={(e) => setF({ ...f, password: e.target.value })}
              required
              minLength={first ? 8 : 1}
              autoComplete={first ? "new-password" : "current-password"}
            />
            <button type="button" className="icon-btn" onClick={() => setShow(!show)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show}>
              {show ? <EyeSlashIcon size={16} /> : <EyeIcon size={16} />}
            </button>
          </span>
        </label>
        <button type="submit" className="btn btn-primary" disabled={auth.isPending}>
          {auth.isPending ? "Signing in…" : first ? "Create and sign in" : "Sign in"}
        </button>
        <p className="ad-auth-foot">
          <LockKeyIcon size={13} />
          Read-only. Sessions last 12 hours.
        </p>
      </form>
      <a className="ad-auth-out" href={APP_URL}>
        Looking for dotrix? Open the app
        <ArrowUpRightIcon size={13} />
      </a>
    </main>
  );
}

export function App() {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(false);
  const [booting, setBooting] = useState(true);
  const [page, go] = usePage();

  const me = useQuery({ queryKey: ["me"], queryFn: () => call<Me>("/admin/me"), enabled: signedIn, retry: false });

  // On load, a valid refresh cookie signs back in without the form.
  useEffect(() => {
    refreshSession()
      .then((ok) => ok && setSignedIn(true))
      .finally(() => setBooting(false));
  }, []);

  const signOut = () => {
    // Revoke before dropping the UI's session, so the cookie is still sent.
    void rawCall<void>("/admin/logout", { method: "POST" }).catch(() => undefined);
    setSignedIn(false);
    qc.clear();
  };

  if (booting || (signedIn && me.isPending)) return <p className="state boot">Loading…</p>;
  if (!signedIn || me.isError || !me.data)
    return (
      <Login
        onAuth={() => {
          qc.removeQueries({ queryKey: ["me"] });
          setSignedIn(true);
        }}
      />
    );

  return (
    <div className="ad-shell">
      <aside className="ad-side">
        <span className="ad-brand">
          <Mark />
          dotrix <em>admin</em>
        </span>
        <nav aria-label="Pages">
          {PAGES.map(({ id, label, icon: I }) => (
            <a key={id} href={`#/${id}`} className={page === id ? "on" : undefined} aria-current={page === id ? "page" : undefined}>
              <I size={17} weight={page === id ? "fill" : "regular"} />
              <span>{label}</span>
            </a>
          ))}
        </nav>
        <div className="ad-side-foot">
          <span className="ad-who">
            <b>{me.data.name}</b>
            <span>{me.data.email}</span>
          </span>
          <button type="button" className="icon-btn" onClick={signOut} title="Sign out" aria-label="Sign out">
            <SignOutIcon size={17} />
          </button>
        </div>
      </aside>
      <main className="ad-main">
        <Suspense fallback={<p className="state">Loading…</p>}>
          {page === "overview" && <Overview go={go} />}
          {page === "runs" && <Runs />}
          {page === "failures" && <FailuresPage />}
          {page === "coding" && <CodingPage />}
          {page === "workspaces" && <WorkspacesPage />}
          {page === "audit" && <AuditPage />}
        </Suspense>
      </main>
    </div>
  );
}
