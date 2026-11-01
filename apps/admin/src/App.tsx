// dotrix admin: the console for whoever operates dotrix. It has its own accounts and sign-in
// (/v1/ops/*, never the web app's session) and reads the whole platform's health and use, across
// every workspace, without what people wrote.
import { ChartBarIcon, CodeIcon, ListBulletsIcon, ScrollIcon, SignOutIcon, SquaresFourIcon, WarningOctagonIcon, type Icon } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { call, rawCall, refreshSession, type Me } from "./api";
import { AuditPage, CodingPage, FailuresPage, Overview, Runs, WorkspacesPage } from "./pages";

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
  const boot = useQuery({ queryKey: ["bootstrap"], queryFn: () => rawCall<{ enabled: boolean }>("/ops/bootstrap"), staleTime: 60_000 });
  const first = boot.data?.enabled === true;
  const [f, setF] = useState({ email: "", name: "", password: "" });
  const auth = useMutation({
    mutationFn: () =>
      rawCall<void>(first ? "/ops/signup" : "/ops/login", {
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
      <form className="ad-auth-card" onSubmit={submit}>
        <span className="ad-auth-brand">
          <Mark size={22} />
          dotrix <em>admin</em>
        </span>
        <h1>{first ? "Create the first admin account" : "Sign in"}</h1>
        <p className="ad-auth-sub">
          {first
            ? "This form is open only until the first account exists. Its sign-in is separate from the dotrix app's."
            : "For whoever operates dotrix. Your dotrix app account doesn't sign in here."}
        </p>
        {first && (
          <label>
            Name
            <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required autoComplete="name" />
          </label>
        )}
        <label>
          Email
          <input className="input" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required autoComplete="username" />
        </label>
        <label>
          Password{first ? " (at least 8 characters)" : ""}
          <input
            className="input"
            type="password"
            value={f.password}
            onChange={(e) => setF({ ...f, password: e.target.value })}
            required
            minLength={first ? 8 : 1}
            autoComplete={first ? "new-password" : "current-password"}
          />
        </label>
        {auth.isError && <p className="ad-auth-error">{auth.error.message}</p>}
        <button type="submit" className="btn btn-primary" disabled={auth.isPending}>
          {auth.isPending ? "One moment…" : first ? "Create and sign in" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export function App() {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(false);
  const [booting, setBooting] = useState(true);
  const [page, go] = usePage();

  const me = useQuery({ queryKey: ["me"], queryFn: () => call<Me>("/ops/me"), enabled: signedIn, retry: false });

  // On load, a valid refresh cookie signs back in without the form.
  useEffect(() => {
    refreshSession()
      .then((ok) => ok && setSignedIn(true))
      .finally(() => setBooting(false));
  }, []);

  const signOut = () => {
    // Revoke before dropping the UI's session, so the cookie is still sent.
    void rawCall<void>("/ops/logout", { method: "POST" }).catch(() => undefined);
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
        {page === "overview" && <Overview go={go} />}
        {page === "runs" && <Runs />}
        {page === "failures" && <FailuresPage />}
        {page === "coding" && <CodingPage />}
        {page === "workspaces" && <WorkspacesPage />}
        {page === "audit" && <AuditPage />}
      </main>
    </div>
  );
}
