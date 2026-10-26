// dotrix Ops (phase 1): a separate app from the web app, with its own accounts and sign-in
// (POST /v1/ops/*). An ops account is bound to the workspace proven at sign-up; everything it
// sees stays inside that workspace.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@dotrix/ui/components/card";
import { Input } from "@dotrix/ui/components/input";
import { Label } from "@dotrix/ui/components/label";
import { Tabs, TabsList, TabsTrigger } from "@dotrix/ui/components/tabs";

type Problem = { detail?: string };

// Both tokens live in httpOnly, SameSite=Strict cookies. The refresh cookie is scoped
// to /v1/ops/refresh and browser tabs serialize rotation with a Web Lock.
let refreshing: Promise<string | null> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    const refresh = () => rawCall<void>("/ops/refresh", { method: "POST" }).then(() => "ok");
    return navigator.locks ? navigator.locks.request("dotrix-ops-refresh", refresh) : refresh();
  })()
    .catch(() => null)
    .finally(() => (refreshing = null));
  return (await refreshing) !== null;
}

async function rawCall<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(`/v1${path}`, {
    method: options.method ?? "GET",
    headers: {
      "X-Requested-With": "dotrix-ops",
      ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  const data = res.status === 204 ? undefined : await res.json().catch(() => undefined);
  if (!res.ok) {
    const err = new Error((data as Problem | undefined)?.detail ?? `Request failed (${res.status})`);
    (err as Error & { status?: number }).status = res.status;
    throw err;
  }
  return data as T;
}

async function call<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  try {
    return await rawCall<T>(path, options);
  } catch (e) {
    if ((e as Error & { status?: number }).status !== 401) throw e;
    if (!(await refreshSession())) throw e;
    return rawCall<T>(path, options);
  }
}

const num = (n: number | null | undefined) => (n ?? 0).toLocaleString();
const bytes = (n: number) =>
  n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(1)} GB` : n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.round(n / 1024)} KB`;
const fmt = (s: string) => new Date(s).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  failed: "destructive",
  recovery_required: "destructive",
  running: "default",
  queued: "default",
  awaiting_approval: "secondary",
  changes_ready: "secondary",
  rejected: "secondary",
  stopped: "secondary",
};

type Me = { email: string; name: string; workspace: { id: string; name: string; slug: string; kind: string } };
type Group = { total: number; active: number; waiting: number; failed_7d: number; input_tokens_7d: number; output_tokens_7d: number };
type Overview = {
  jobs: string;
  stuck: number;
  counts: { projects: number; members: number; documents: number; document_bytes: number; coding_runners: number };
  chat: Group & { model_calls_7d: number };
  coding: Group & { cost_usd_7d: number | null };
  queue: { pending: number; oldest_pending_seconds: number | null; discarded_7d: number };
};
type Run = {
  kind: string;
  id: string;
  status: string;
  label: string;
  agent: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  error: string | null;
  automation: boolean;
  created_at: string;
};
type AuditEvent = { id: string; action: string; target: string | null; actor_user_id: string | null; agent: string | null; created_at: string };

function Stat({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className={`text-lg font-semibold ${warn ? "text-amber-600" : ""}`}>{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}

function GroupCard({ title, g, cost }: { title: string; g: Group; cost?: string | null }) {
  return (
    <Card className="min-w-72 flex-1">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-5">
        <Stat label="Total" value={g.total} />
        <Stat label="Active" value={g.active} />
        <Stat label="Waiting" value={g.waiting} warn={g.waiting > 0} />
        <Stat label="Failed (7d)" value={g.failed_7d} warn={g.failed_7d > 0} />
        {cost !== undefined && <Stat label="Cost (7d)" value={cost ?? "—"} />}
      </CardContent>
    </Card>
  );
}

function Login({ onAuth }: { onAuth: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [f, setF] = useState({ owner_email: "", owner_password: "", email: "", name: "", password: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const auth = useMutation({
    mutationFn: () =>
      rawCall<void>(mode === "login" ? "/ops/login" : "/ops/signup", {
        method: "POST",
        body: mode === "login" ? { email: f.email, password: f.password } : f,
      }),
    onSuccess: onAuth,
  });
  const submit = (e: FormEvent) => (e.preventDefault(), auth.mutate());
  return (
    <div className="ops-auth">
      <h1>dotrix ops</h1>
      <p className="sub">Workspace operations, bound to one workspace.</p>
      <Tabs value={mode} onValueChange={(v) => setMode(v as "login" | "signup")}>
        <TabsList className="mb-4 w-full">
          <TabsTrigger value="login">Sign in</TabsTrigger>
          <TabsTrigger value="signup">Create ops account</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card className="border-0 bg-transparent shadow-none">
        <CardContent className="flex flex-col gap-3 px-0 pt-0">
          <form onSubmit={submit} className="flex flex-col gap-3">
            {mode === "signup" && (
              <>
                <p className="text-xs text-muted-foreground">
                  Prove you own the workspace once — your dotrix sign-in — then this ops account is fully separate.
                </p>
                <div className="grid gap-1.5">
                  <Label htmlFor="oe">Your dotrix email</Label>
                  <Input id="oe" type="email" value={f.owner_email} onChange={set("owner_email")} required />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="op">Your dotrix password</Label>
                  <Input id="op" type="password" value={f.owner_password} onChange={set("owner_password")} required />
                </div>
                <div className="grid gap-1.5">
                  <Label htmlFor="nm">Ops name</Label>
                  <Input id="nm" value={f.name} onChange={set("name")} required />
                </div>
              </>
            )}
            <div className="grid gap-1.5">
              <Label htmlFor="em">{mode === "signup" ? "Ops email" : "Email"}</Label>
              <Input id="em" type="email" value={f.email} onChange={set("email")} required />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pw">Password{mode === "signup" ? " (8+)" : ""}</Label>
              <Input id="pw" type="password" value={f.password} onChange={set("password")} required minLength={mode === "signup" ? 8 : 1} />
            </div>
            {auth.isError && <p className="text-xs text-destructive">{auth.error.message}</p>}
            <Button type="submit" disabled={auth.isPending}>
              {auth.isPending ? "…" : mode === "login" ? "Sign in" : "Create & sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function Overview() {
  const q = useQuery({
    queryKey: ["overview"],
    queryFn: () => call<Overview>("/ops/observe/overview"),
    refetchInterval: 15_000,
  });
  if (q.isPending) return <p className="text-sm text-muted-foreground">Reading the workspace…</p>;
  if (q.isError) return <p className="text-sm text-destructive">{q.error.message}</p>;
  const d = q.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        <Card className="min-w-72 flex-1">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Workspace</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-5">
            <Stat label="Projects" value={d.counts.projects} />
            <Stat label="Members" value={d.counts.members} />
            <Stat label="Documents" value={`${d.counts.documents} (${bytes(d.counts.document_bytes)})`} />
            <Stat label="Runners" value={d.counts.coding_runners} />
            <Stat label="Jobs" value={d.jobs} />
            <Stat label="Stuck runs" value={d.stuck} warn={d.stuck > 0} />
          </CardContent>
        </Card>
        <Card className="min-w-72 flex-1">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Run queue & tokens (7d)</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-5">
            <Stat label="Pending" value={d.queue.pending} warn={d.queue.pending > 0} />
            <Stat label="Oldest wait" value={d.queue.oldest_pending_seconds != null ? `${Math.round(d.queue.oldest_pending_seconds)}s` : "—"} />
            <Stat label="Given up (7d)" value={d.queue.discarded_7d} warn={d.queue.discarded_7d > 0} />
            <Stat label="Tokens in" value={num(d.chat.input_tokens_7d + d.coding.input_tokens_7d)} />
            <Stat label="Tokens out" value={num(d.chat.output_tokens_7d + d.coding.output_tokens_7d)} />
          </CardContent>
        </Card>
      </div>
      <div className="flex flex-wrap gap-3">
        <GroupCard title="Conversations (chat runs)" g={d.chat} />
        <GroupCard title="Coding turns" g={d.coding} cost={d.coding.cost_usd_7d != null ? `$${d.coding.cost_usd_7d.toFixed(2)}` : "—"} />
      </div>
    </div>
  );
}

function Runs() {
  const [kind, setKind] = useState<"all" | "chat" | "coding">("all");
  const [before, setBefore] = useState<{ at: string; id: string }>();
  const q = useQuery({
    queryKey: ["runs", kind, before?.at, before?.id],
    queryFn: () =>
      call<Run[]>(`/ops/observe/runs?limit=50${kind === "all" ? "" : `&kind=${kind}`}${before ? `&before=${before.at}&before_id=${before.id}` : ""}`),
    placeholderData: (prev) => prev,
  });
  return (
    <div>
      <Tabs value={kind} onValueChange={(v) => (setKind(v as typeof kind), setBefore(undefined))}>
        <TabsList className="mb-3">
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="coding">Coding</TabsTrigger>
        </TabsList>
      </Tabs>
      {q.isPending ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : q.isError ? (
        <p className="text-sm text-destructive">{q.error.message}</p>
      ) : !q.data.length ? (
        <p className="text-sm text-muted-foreground">No runs yet.</p>
      ) : (
        <Card>
          <CardContent className="pt-4">
            <div className="flex gap-3 border-b pb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              <span className="w-12">Kind</span>
              <span className="w-32">Status</span>
              <span className="flex-1">Run</span>
              <span className="w-20">Agent</span>
              <span className="w-24">Tokens</span>
              <span className="w-14">Cost</span>
              <span className="w-28">When</span>
            </div>
            {q.data.map((r) => (
              <div key={r.id} className="flex items-center gap-3 border-b py-1.5 text-xs last:border-0">
                <span className="w-12 text-muted-foreground">{r.kind}</span>
                <span className="w-32">
                  <Badge variant={STATUS_VARIANT[r.status] ?? "outline"}>
                    {r.status.replaceAll("_", " ")}
                    {r.automation ? " ·auto" : ""}
                  </Badge>
                </span>
                <span className="flex-1 truncate" title={r.error ?? undefined}>
                  {r.label}
                  {r.error ? ` — ${r.error}` : ""}
                </span>
                <span className="w-20 truncate text-muted-foreground">{r.agent ?? "—"}</span>
                <span className="w-24 text-muted-foreground">
                  {num(r.input_tokens)} / {num(r.output_tokens)}
                </span>
                <span className="w-14 text-muted-foreground">{r.cost_usd != null ? `$${r.cost_usd.toFixed(3)}` : "—"}</span>
                <span className="w-28 text-muted-foreground">{fmt(r.created_at)}</span>
              </div>
            ))}
            {q.data.length === 50 && (
              <Button
                variant="outline"
                className="mt-3"
                onClick={() => {
                  const last = q.data.at(-1)!;
                  setBefore({ at: last.created_at, id: last.id });
                }}
              >
                Older runs
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Audit() {
  const [action, setAction] = useState("");
  const [older, setOlder] = useState<AuditEvent[][]>([]);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const q = useQuery({
    queryKey: ["audit", action],
    queryFn: () => call<AuditEvent[]>(`/ops/audit?limit=100${action ? `&action=${encodeURIComponent(action)}` : ""}`),
    placeholderData: (prev) => prev,
  });
  const events = [...(q.data ?? []), ...older.flat()];
  const last = events.at(-1);
  const loadOlder = async () => {
    if (!last) return;
    setLoadingOlder(true);
    try {
      const next = await call<AuditEvent[]>(
        `/ops/audit?limit=100&before=${encodeURIComponent(last.created_at)}${action ? `&action=${encodeURIComponent(action)}` : ""}`,
      );
      setOlder((p) => [...p, next]);
    } finally {
      setLoadingOlder(false);
    }
  };
  return (
    <div>
      <Input
        className="mb-3 max-w-xs"
        placeholder="Filter by action (e.g. issue.updated)"
        value={action}
        onChange={(e) => (setAction(e.target.value), setOlder([]))}
      />
      <Card>
        <CardContent className="pt-4">
          {q.isPending ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : q.isError ? (
            <p className="text-sm text-destructive">{q.error.message}</p>
          ) : !events.length ? (
            <p className="text-sm text-muted-foreground">Nothing recorded.</p>
          ) : (
            <>
              {events.map((e) => (
                <div key={e.id} className="flex items-center gap-3 border-b py-1.5 text-xs last:border-0">
                  <b className="w-52 truncate">{e.action}</b>
                  <span className="w-24 text-muted-foreground">{e.target ?? "—"}</span>
                  <span className="flex-1 text-muted-foreground">{e.agent ? `agent ${e.agent}` : "person"}</span>
                  <span className="w-28 text-right text-muted-foreground">{fmt(e.created_at)}</span>
                </div>
              ))}
              {(older.at(-1)?.length ?? q.data?.length ?? 0) === 100 && (
                <Button variant="outline" className="mt-3" disabled={loadingOlder} onClick={loadOlder}>
                  {loadingOlder ? "Loading…" : "Older events"}
                </Button>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Organisation({ me }: { me: Me }) {
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => call("/ops/organization", { method: "POST", body: { name: name.trim() } }),
  });
  if (create.isSuccess)
    return (
      <Card className="max-w-lg">
        <CardContent className="pt-5">
          <b>{name.trim()} is an organisation now — your account owns it.</b>
          <p className="mt-1 text-sm text-muted-foreground">
            Open it in the app from the workspace switcher; members and invites live under Settings → Members.
            {me.workspace.name} stays your personal workspace.
          </p>
        </CardContent>
      </Card>
    );
  return (
    <Card className="max-w-lg">
      <CardHeader>
        <CardTitle className="text-base">Create an organisation workspace</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          A new, separate workspace your account owns — for a team: invites, roles, many projects. {me.workspace.name} stays your personal workspace; nothing
          moves or converts.
        </p>
        <div className="grid gap-1.5">
          <Label htmlFor="orgname">Organisation name</Label>
          <Input id="orgname" value={name} placeholder="Your team's name" onChange={(e) => setName(e.target.value)} />
        </div>
        {create.isError && <p className="text-xs text-destructive">{create.error.message}</p>}
        <div>
          <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Creating…" : "Create the organisation"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function App() {
  const qc = useQueryClient();
  const [signedIn, setSignedIn] = useState(false);
  const [booting, setBooting] = useState(true);
  const [tab, setTab] = useState("overview");
  const auth = () => {
    qc.removeQueries({ queryKey: ["me"] });
    setSignedIn(true);
  };
  const signOut = () => {
    // Revocation happens before removing the UI session, so the cookie is still sent.
    void rawCall<void>("/ops/logout", { method: "POST" }).catch(() => undefined);
    setSignedIn(false);
    qc.clear();
  };

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => call<Me>("/ops/me"),
    enabled: signedIn,
    retry: false,
  });

  // On load: a valid refresh cookie silently signs back in.
  useEffect(() => {
    refreshSession()
      .then((ok) => ok && setSignedIn(true))
      .finally(() => setBooting(false));
  }, []);

  if (booting || (signedIn && me.isPending)) return <p className="p-10 text-sm text-muted-foreground">Loading…</p>;
  if (!signedIn || me.isError || !me.data) return <Login onAuth={auth} />;
  const m = me.data;

  return (
    <>
      <header className="ops-topbar">
        <div className="ops-brand">
          dotrix ops
          <span>
            {m.name} · {m.workspace.name} ({m.workspace.kind})
          </span>
        </div>
        <Button variant="outline" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </header>
      <div className="ops-page">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="mb-4">
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="runs">Runs</TabsTrigger>
            <TabsTrigger value="audit">Audit log</TabsTrigger>
            <TabsTrigger value="org">Organisation</TabsTrigger>
          </TabsList>
        </Tabs>
        {tab === "overview" && <Overview />}
        {tab === "runs" && <Runs />}
        {tab === "audit" && <Audit />}
        {tab === "org" && <Organisation me={m} />}
      </div>
    </>
  );
}
