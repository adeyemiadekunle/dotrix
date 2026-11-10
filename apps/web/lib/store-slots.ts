// The store's lists in a real workspace, read from the query cache as it is now. `data/live.ts` makes
// each of `D().tasks`, `D().members`, … a getter over one of these, so nothing copies a query into the
// store and a lookup never lags behind the cache. The hooks that fetch these queries (StoreBridge
// mounts them) keep them loaded and fresh; this file only reads.
//
// A slot builds its list once per version of the cached data and gives back that same array (and the
// same objects in it) until the data changes, like the old mirror did: code that changes an item in
// place, or replaces the list (`D().members = …`), sees its change until the next refetch brings the
// API's answer. `forgetSlots()` drops those changes at once (a write the API refused).
import type { Schemas } from "./api";
import type { WorkspaceIssueFilters } from "./issues";
import { queryClient } from "./queryClient";
import { ms, toActivity, toAgent, toAudit, toAutomation, toCodingSession, toFile, toMember, toNotif, toProject, toTask, toThread } from "./view-models";
import type { Data, KnowledgeFile, Member } from "@/src/data/types";

/** The issues query every task lookup reads: all of a workspace's issues, archived ones too. */
export const EVERY_ISSUE: WorkspaceIssueFilters = { archived: "include", order: "created" };

type Key = readonly unknown[];
const cached = <T = unknown>(key: Key): T | undefined => queryClient.getQueryData<T>(key);
/** Whether a query has answered, with data or for good with an error (a project whose documents failed adds none). */
const settled = (key: Key) => cached(key) !== undefined || queryClient.getQueryState(key)?.status === "error";

interface Slot<T> {
  /** What the list is made from, or undefined while what it needs hasn't loaded. */
  inputs: (ws: string) => unknown[] | undefined;
  build: (inputs: unknown[]) => T[];
}
const slot = <T>(s: Slot<T>) => s;

type Project = Schemas["ProjectRead"];
const projects = (ws: string) => cached<Project[]>(["projects", ws]);
/** One query per visible project (documents, knowledge, automations): ready once each has answered. */
const perProject = (ws: string, kind: string) => {
  const ps = projects(ws);
  if (!ps || !ps.every((p) => settled([kind, p.id]))) return undefined;
  return [ps, ...ps.map((p) => cached([kind, p.id]))];
};

const toInvited = (i: Schemas["InviteRead"]): Member => ({
  id: "invite:" + i.id,
  name: (i.email ?? "")
    .split("@")[0]!
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase()),
  email: i.email ?? "",
  role: ({ owner: "Owner", admin: "Admin", member: "Member", guest: "Guest" } as const)[i.role] ?? "Member",
  title: "",
  c: "#6B7280",
  status: "invited",
  last: null,
  tz: "",
});

const SLOTS = {
  tasks: slot({
    inputs: (ws) => {
      const rows = cached(["issues", "workspace", ws, EVERY_ISSUE]);
      return rows === undefined ? undefined : [rows, cached(["issues", "workspace", ws, "starred-keys"])];
    },
    build: ([rows, starred]) => {
      const fav = new Set(((starred ?? []) as Schemas["WorkspaceIssue"][]).map((i) => i.key));
      return (rows as Schemas["WorkspaceIssue"][]).map((i) => ({ ...toTask(i, i.project_id, i.rank), fav: fav.has(i.key) }));
    },
  }),
  members: slot({
    inputs: (ws) => {
      const members = cached(["members", ws]);
      return members === undefined ? undefined : [members, cached(["members", ws, "invites"])];
    },
    build: ([members, invites]) => [
      ...(members as Schemas["MemberRead"][]).map(toMember),
      ...((invites ?? []) as Schemas["InviteRead"][]).filter((i) => i.kind === "email" && i.email).map(toInvited),
    ],
  }),
  agents: slot({
    inputs: (ws) => {
      const as = cached(["agents", ws]);
      return as === undefined ? undefined : [as];
    },
    build: ([agents]) => (agents as Schemas["AgentRead"][]).map(toAgent),
  }),
  projects: slot({
    inputs: (ws) => {
      const ps = projects(ws);
      const members = cached(["members", ws, "raw"]);
      return ps === undefined || members === undefined ? undefined : [ps, members, cached(["projects", ws, "starred"])];
    },
    build: ([ps, members, starred]) => {
      const stars = new Set((starred ?? []) as string[]);
      return (ps as Project[]).map((p) => toProject(p, members as Schemas["MemberRead"][], stars));
    },
  }),
  notifs: slot({
    inputs: (ws) => {
      const ns = cached(["notifications", ws, "list", "all"]);
      return ns === undefined ? undefined : [ns];
    },
    build: ([ns]) => (ns as Schemas["NotificationRead"][]).map(toNotif),
  }),
  activity: slot({
    inputs: (ws) => {
      const feed = cached(["activity", "workspace", ws]);
      return feed === undefined ? undefined : [feed];
    },
    build: ([feed]) => (feed as Schemas["ActivityItem"][]).map(toActivity),
  }),
  threads: slot({
    inputs: (ws) => {
      const cs = cached(["conversations", ws]);
      return cs === undefined ? undefined : [cs];
    },
    build: ([cs]) => (cs as Schemas["WorkspaceConversation"][]).map(toThread),
  }),
  coding: slot({
    inputs: (ws) => {
      const ss = cached(["coding-sessions", ws]);
      return ss === undefined ? undefined : [ss];
    },
    build: ([ss]) => (ss as Schemas["CodingSessionRead"][]).map(toCodingSession),
  }),
  audit: slot({
    inputs: (ws) => {
      const es = cached(["audit", ws]);
      return es === undefined ? undefined : [es];
    },
    build: ([es]) => (es as Schemas["AuditEventRead"][]).map(toAudit),
  }),
  files: slot({
    inputs: (ws) => perProject(ws, "documents"),
    build: ([ps, ...docs]) => (docs as (Schemas["DocumentRead"][] | undefined)[]).flatMap((d, i) => (d ?? []).map((x) => toFile(x, (ps as Project[])[i]!.id))),
  }),
  knowledge: slot({
    inputs: (ws) => perProject(ws, "knowledge"),
    build: ([ps, ...manifests]) =>
      (manifests as (Schemas["Manifest"] | undefined)[]).flatMap((m, i): KnowledgeFile[] =>
        (m?.files ?? [])
          .filter((f) => !f.deleted)
          .map((f) => ({ path: f.path, project: (ps as Project[])[i]!.id, content: "", version: f.version, by: "", at: ms(f.updated_at) })),
      ),
  }),
  automations: slot({
    inputs: (ws) => perProject(ws, "automations"),
    build: ([, ...autos]) => (autos as (Schemas["AutomationRead"][] | undefined)[]).flatMap((a) => (a ?? []).map(toAutomation)),
  }),
} satisfies { [K in keyof Data]?: Slot<Data[K] extends (infer T)[] ? T : never> };

export type SlotName = keyof typeof SLOTS;
export const SLOT_NAMES = Object.keys(SLOTS) as SlotName[];
type Item<K extends SlotName> = Data[K] extends (infer T)[] ? T : never;

/** The list last built for each slot, with what it was built from. */
const built = new Map<SlotName, { ws: string; inputs: unknown[]; value: unknown[] }>();
const same = (a: unknown[], b: unknown[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** A slot's list from the cache as it is now; undefined until what it needs has loaded. */
export function readSlot<K extends SlotName>(name: K, ws: string): Item<K>[] | undefined {
  const s = SLOTS[name] as Slot<Item<K>>;
  const inputs = s.inputs(ws);
  if (!inputs) return undefined;
  const last = built.get(name);
  if (last && last.ws === ws && same(last.inputs, inputs)) return last.value as Item<K>[];
  const value = s.build(inputs);
  built.set(name, { ws, inputs, value });
  return value;
}

/** Replace a slot's list until the cache's data changes. False while the slot hasn't loaded (the caller keeps its own list). */
export function writeSlot<K extends SlotName>(name: K, ws: string, value: Item<K>[]): boolean {
  const inputs = SLOTS[name].inputs(ws);
  if (!inputs) return false;
  built.set(name, { ws, inputs, value });
  return true;
}

/** Build every slot again from the cache, dropping changes that never reached it. */
export function forgetSlots() {
  built.clear();
}
