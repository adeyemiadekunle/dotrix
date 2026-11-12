// dotrix admin: the console for whoever operates dotrix. It has its own accounts and sign-in
// (/v1/admin/*, never the web app's session) and reads the whole platform's health and use, across
// every workspace, without what people wrote.
import {
  ArrowUpRightIcon,
  ChartBarIcon,
  CodeIcon,
  CpuIcon,
  EyeIcon,
  EyeSlashIcon,
  ListBulletsIcon,
  LockKeyIcon,
  FingerprintIcon,
  ScrollIcon,
  SignOutIcon,
  SquaresFourIcon,
  UsersThreeIcon,
  WarningCircleIcon,
  WarningOctagonIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";

import { call, rawCall, refreshSession, send, type LoginChallenge, type Me } from "./api";

// The pages (and their charts and tables) load after sign-in, so the sign-in page is small and quick.
const pages = () => import("./pages");
const Overview = lazy(() => pages().then((m) => ({ default: m.Overview })));
const Runs = lazy(() => pages().then((m) => ({ default: m.Runs })));
const FailuresPage = lazy(() => pages().then((m) => ({ default: m.FailuresPage })));
const CodingPage = lazy(() => pages().then((m) => ({ default: m.CodingPage })));
const ModelsPage = lazy(() => pages().then((m) => ({ default: m.ModelsPage })));
const WorkspacesPage = lazy(() => pages().then((m) => ({ default: m.WorkspacesPage })));
const AuditPage = lazy(() => pages().then((m) => ({ default: m.AuditPage })));
const TrailPage = lazy(() => pages().then((m) => ({ default: m.TrailPage })));
const AdminsPage = lazy(() => pages().then((m) => ({ default: m.AdminsPage })));

/** Where people who use dotrix sign in: the web app (`VITE_APP_URL`, set at build time). */
const APP_URL = (import.meta.env.VITE_APP_URL as string | undefined) ?? "https://app.dotrix.cc";

const PAGES: { id: string; label: string; icon: Icon; owner?: boolean }[] = [
  { id: "overview", label: "Overview", icon: ChartBarIcon },
  { id: "runs", label: "Runs", icon: ListBulletsIcon },
  { id: "failures", label: "Failures", icon: WarningOctagonIcon },
  { id: "coding", label: "Coding", icon: CodeIcon },
  { id: "models", label: "Models", icon: CpuIcon },
  { id: "workspaces", label: "Workspaces", icon: SquaresFourIcon },
  { id: "audit", label: "Audit log", icon: ScrollIcon },
  { id: "admins", label: "Admins", icon: UsersThreeIcon, owner: true },
  { id: "trail", label: "Admin activity", icon: FingerprintIcon, owner: true },
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
    const id = location.hash.replace(/^#\/?/, "").split("?")[0];
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
  const boot = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => rawCall<{ enabled: boolean; token_required?: boolean }>("/admin/bootstrap"),
    staleTime: 60_000,
  });
  const first = boot.data?.enabled === true;
  const [f, setF] = useState({ email: "", name: "", password: "", token: "" });
  const [show, setShow] = useState(false);
  // The challenge lives in memory only; it is not a session and expires in five minutes.
  const [challenge, setChallenge] = useState<string | null>(null);
  const auth = useMutation({
    mutationFn: () =>
      rawCall<LoginChallenge | undefined>(first ? "/admin/signup" : "/admin/login", {
        method: "POST",
        body: first ? { email: f.email, name: f.name, password: f.password, bootstrap_token: f.token || undefined } : { email: f.email, password: f.password },
      }),
    onSuccess: (result) => {
      if (result?.challenge) setChallenge(result.challenge);
      else onAuth();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    auth.mutate();
  };
  if (challenge) return <SecondFactor challenge={challenge} onAuth={onAuth} onBack={() => setChallenge(null)} />;
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
          {first && boot.data?.token_required && <p className="ad-auth-sub">Ask whoever deployed dotrix for the setup token (DOTRIX_ADMIN_BOOTSTRAP_TOKEN).</p>}
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
        {first && boot.data?.token_required && (
          <label>
            Setup token
            <input className="input" type="password" value={f.token} onChange={(e) => setF({ ...f, token: e.target.value })} required autoComplete="off" />
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
          Sessions last 12 hours.
        </p>
      </form>
      <a className="ad-auth-out" href={APP_URL}>
        Looking for dotrix? Open the app
        <ArrowUpRightIcon size={13} />
      </a>
    </main>
  );
}

/** The second step of sign-in: a code from the authenticator app, or a recovery code. */
function SecondFactor({ challenge, onAuth, onBack }: { challenge: string; onAuth: () => void; onBack: () => void }) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const verify = useMutation({
    mutationFn: () => rawCall<void>("/admin/login/verify", { method: "POST", body: { challenge, code: code.trim() } }),
    onSuccess: onAuth,
  });
  return (
    <main className="ad-auth">
      <div className="ad-auth-bg" aria-hidden="true" />
      <form
        className="ad-auth-card"
        aria-busy={verify.isPending}
        onSubmit={(e) => {
          e.preventDefault();
          verify.mutate();
        }}
      >
        <span className="ad-auth-brand">
          <Mark size={22} />
          dotrix <em>admin</em>
        </span>
        <div>
          <h1>{recovery ? "Use a recovery code" : "Enter your code"}</h1>
          <p className="ad-auth-sub">{recovery ? "Each recovery code works once." : "The 6-digit code from your authenticator app."}</p>
        </div>
        {verify.isError && (
          <p className="ad-auth-error" role="alert">
            <WarningCircleIcon size={16} weight="fill" />
            {verify.error.message}
          </p>
        )}
        <label>
          {recovery ? "Recovery code" : "Code"}
          <input
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            autoFocus
            autoComplete={recovery ? "off" : "one-time-code"}
            inputMode={recovery ? "text" : "numeric"}
            maxLength={recovery ? 100 : 6}
            minLength={recovery ? 6 : 6}
            pattern={recovery ? undefined : "[0-9]{6}"}
          />
        </label>
        <button type="submit" className="btn btn-primary" disabled={verify.isPending}>
          {verify.isPending ? "Checking…" : "Sign in"}
        </button>
        <p className="ad-auth-foot">
          <button
            type="button"
            className="link"
            onClick={() => {
              setRecovery(!recovery);
              setCode("");
              verify.reset();
            }}
          >
            {recovery ? "Use the authenticator app" : "Use a recovery code"}
          </button>
          {" · "}
          <button type="button" className="link" onClick={onBack}>
            Start over
          </button>
        </p>
      </form>
    </main>
  );
}

/** Required once per admin: add the secret to an authenticator app, confirm with a code, keep the
 * recovery codes. The secret and codes are shown here only and held in memory, never stored in the browser. */
function Enrol({ onDone, onSignOut }: { onDone: () => void; onSignOut: () => void }) {
  const [code, setCode] = useState("");
  const start = useMutation({ mutationFn: () => send<{ secret: string; otpauth_uri: string }>("/admin/me/two-factor/start", "POST") });
  const confirm = useMutation({
    mutationFn: () => send<{ recovery_codes: string[] }>("/admin/me/two-factor/confirm", "POST", { code: code.trim() }),
  });
  return (
    <main className="ad-auth">
      <div className="ad-auth-bg" aria-hidden="true" />
      <form
        className="ad-auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (!confirm.isPending) confirm.mutate();
        }}
      >
        <span className="ad-auth-brand">
          <Mark size={22} />
          dotrix <em>admin</em>
        </span>
        <h1>Set up two-factor sign-in</h1>
        {confirm.data ? (
          <>
            <p className="ad-auth-sub">Save these recovery codes somewhere safe. Each works once if you lose your device. They are not shown again.</p>
            <ul className="mono ad-codes">
              {confirm.data.recovery_codes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
            <button type="button" className="btn btn-primary" onClick={onDone}>
              I&apos;ve saved these
            </button>
          </>
        ) : !start.data ? (
          <>
            <p className="ad-auth-sub">Admins sign in with a code from an authenticator app as well as a password. Set it up now to continue.</p>
            {start.isError && (
              <p className="ad-auth-error" role="alert">
                <WarningCircleIcon size={16} weight="fill" />
                {start.error.message}
              </p>
            )}
            <button type="button" className="btn btn-primary" disabled={start.isPending} onClick={() => start.mutate()}>
              {start.isPending ? "Starting…" : "Set up an authenticator app"}
            </button>
          </>
        ) : (
          <>
            <p className="ad-auth-sub">
              Add this key to your authenticator app (a time-based code, 6 digits), or <a href={start.data.otpauth_uri}>open the setup link</a> on a device that
              has one.
            </p>
            <p className="mono ad-secret" aria-label="Setup key">
              {start.data.secret}
            </p>
            {confirm.isError && (
              <p className="ad-auth-error" role="alert">
                <WarningCircleIcon size={16} weight="fill" />
                {confirm.error.message}
              </p>
            )}
            <label>
              Code from the app
              <input
                className="input"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                autoFocus
                autoComplete="one-time-code"
                inputMode="numeric"
                maxLength={6}
                pattern="[0-9]{6}"
              />
            </label>
            <button type="submit" className="btn btn-primary" disabled={confirm.isPending}>
              {confirm.isPending ? "Checking…" : "Turn on two-factor sign-in"}
            </button>
          </>
        )}
        {!confirm.data && (
          <p className="ad-auth-foot">
            <button type="button" className="link" onClick={onSignOut}>
              Sign out
            </button>
          </p>
        )}
      </form>
    </main>
  );
}

/** The token of an invite link (`#/accept?token=…`), read from the address; kept in memory only. */
function inviteToken(): string | null {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return path === "accept" ? new URLSearchParams(query).get("token") : null;
}

function leaveInvite() {
  history.replaceState(null, "", location.pathname + location.search);
}

function Accept({ token, onAuth }: { token: string; onAuth: () => void }) {
  const invite = useQuery({
    queryKey: ["invite-preview"],
    queryFn: () => rawCall<{ email: string; role: string }>("/admin/invites/preview", { method: "POST", body: { token } }),
    retry: false,
    staleTime: Infinity,
  });
  const [f, setF] = useState({ name: "", password: "", again: "" });
  const mismatch = f.again !== "" && f.again !== f.password;
  const accept = useMutation({
    mutationFn: () => rawCall<void>("/admin/invites/accept", { method: "POST", body: { token, name: f.name, password: f.password } }),
    onSuccess: () => {
      leaveInvite();
      onAuth();
    },
  });
  return (
    <main className="ad-auth">
      <div className="ad-auth-bg" aria-hidden="true" />
      <form
        className="ad-auth-card"
        aria-busy={accept.isPending}
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) accept.mutate();
        }}
      >
        <span className="ad-auth-brand">
          <Mark size={22} />
          dotrix <em>admin</em>
        </span>
        {invite.isPending ? (
          <p className="ad-auth-sub">Checking your invite…</p>
        ) : invite.isError ? (
          <>
            <h1>This invite doesn&apos;t work</h1>
            <p className="ad-auth-sub">The link was used, revoked or has expired. Ask an owner for a new one.</p>
            <a className="btn" href={location.pathname} onClick={leaveInvite}>
              Go to sign in
            </a>
          </>
        ) : (
          <>
            <div>
              <h1>Accept your invite</h1>
              <p className="ad-auth-sub">
                You&apos;re joining as {invite.data.role === "owner" ? "an owner" : "a viewer"} with {invite.data.email}. Choose your own password.
              </p>
            </div>
            {accept.isError && (
              <p className="ad-auth-error" role="alert">
                <WarningCircleIcon size={16} weight="fill" />
                {accept.error.message}
              </p>
            )}
            <label>
              Name
              <input className="input" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required autoComplete="name" autoFocus />
            </label>
            <label>
              Password (at least 12 characters)
              <input
                className="input"
                type="password"
                value={f.password}
                onChange={(e) => setF({ ...f, password: e.target.value })}
                required
                minLength={12}
                autoComplete="new-password"
              />
            </label>
            <label>
              Repeat the password
              <input
                className="input"
                type="password"
                value={f.again}
                onChange={(e) => setF({ ...f, again: e.target.value })}
                required
                autoComplete="new-password"
              />
            </label>
            {mismatch && <p className="ad-auth-error">The passwords don&apos;t match.</p>}
            <button type="submit" className="btn btn-primary" disabled={accept.isPending || mismatch}>
              {accept.isPending ? "Creating…" : "Create my account"}
            </button>
          </>
        )}
      </form>
    </main>
  );
}

function ChangePassword({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ current: "", next: "", again: "" });
  const mismatch = f.again !== "" && f.again !== f.next;
  const change = useMutation({
    mutationFn: () => send("/admin/me/password", "POST", { current_password: f.current, new_password: f.next }),
  });
  return (
    <div className="ad-modal" role="dialog" aria-modal="true" aria-label="Change password">
      <form
        className="ad-auth-card"
        onSubmit={(e) => {
          e.preventDefault();
          if (!mismatch) change.mutate();
        }}
      >
        <h1>Change password</h1>
        {change.isSuccess ? (
          <>
            <p className="ad-auth-sub">Done. Your other sessions were signed out.</p>
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </>
        ) : (
          <>
            {change.isError && (
              <p className="ad-auth-error" role="alert">
                <WarningCircleIcon size={16} weight="fill" />
                {change.error.message}
              </p>
            )}
            <label>
              Current password
              <input
                className="input"
                type="password"
                value={f.current}
                onChange={(e) => setF({ ...f, current: e.target.value })}
                required
                autoComplete="current-password"
                autoFocus
              />
            </label>
            <label>
              New password (at least 12 characters)
              <input
                className="input"
                type="password"
                value={f.next}
                onChange={(e) => setF({ ...f, next: e.target.value })}
                required
                minLength={12}
                autoComplete="new-password"
              />
            </label>
            <label>
              Repeat the new password
              <input
                className="input"
                type="password"
                value={f.again}
                onChange={(e) => setF({ ...f, again: e.target.value })}
                required
                autoComplete="new-password"
              />
            </label>
            {mismatch && <p className="ad-auth-error">The passwords don&apos;t match.</p>}
            <div className="ad-actions">
              <button type="button" className="btn" onClick={onClose}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={change.isPending || mismatch}>
                {change.isPending ? "Saving…" : "Change password"}
              </button>
            </div>
          </>
        )}
      </form>
    </div>
  );
}

export function App() {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(false);
  const [booting, setBooting] = useState(true);
  const [page, go] = usePage();
  const [invite] = useState(inviteToken);
  const [changing, setChanging] = useState(false);

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
  if (!signedIn && invite)
    return (
      <Accept
        token={invite}
        onAuth={() => {
          qc.removeQueries({ queryKey: ["me"] });
          setSignedIn(true);
        }}
      />
    );
  if (!signedIn || me.isError || !me.data)
    return (
      <Login
        onAuth={() => {
          qc.removeQueries({ queryKey: ["me"] });
          setSignedIn(true);
        }}
      />
    );

  if (me.data.must_enrol) return <Enrol onDone={() => void qc.invalidateQueries({ queryKey: ["me"] })} onSignOut={signOut} />;

  return (
    <div className="ad-shell">
      <aside className="ad-side">
        <span className="ad-brand">
          <Mark />
          dotrix <em>admin</em>
        </span>
        <nav aria-label="Pages">
          {PAGES.filter((p) => !p.owner || me.data.role === "owner").map(({ id, label, icon: I }) => (
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
          <button type="button" className="icon-btn" onClick={() => setChanging(true)} title="Change password" aria-label="Change password">
            <LockKeyIcon size={17} />
          </button>
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
          {page === "models" && <ModelsPage />}
          {page === "workspaces" && <WorkspacesPage />}
          {page === "audit" && <AuditPage />}
          {page === "trail" && me.data.role === "owner" && <TrailPage />}
          {page === "admins" && me.data.role === "owner" && <AdminsPage meId={me.data.id} />}
        </Suspense>
      </main>
      {changing && <ChangePassword onClose={() => setChanging(false)} />}
    </div>
  );
}
