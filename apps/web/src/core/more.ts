// More of Gr8r's actions (gr8r-studio/src/actions/*.js): undo snapshots, confirmations, modals,
// and what the context menus do (duplicate, archive, delete, rename, share, columns, members,
// files, saved views), with Gr8r's wording and undo.
import { allowed, canInvite } from "./can";
import { PR, PCOLORS } from "./constants";
import { applyPatch, closePop, copy, createTask, guarded, nextKey, openTask } from "./actions";
import { go, routeOf } from "./nav";
import { dOff, uid } from "./utils";
import {
  D,
  DEFAULT_PREFS,
  S,
  allTasks,
  canSee,
  commentsOf,
  logAct,
  me,
  mem,
  mutate,
  proj,
  render,
  save,
  task,
  tasksOf,
  team,
  visibleProjects,
  type Modal,
} from "../data/store";
import { fileDeleted, fileDuplicated, fileRenamed, isLive, projectCreated, projectDeleted, resynced, showDemo, signOutLive, tasksDeleted } from "../data/live";
import { inviteResent, isInvite, memberRemoved, ownershipTransferred } from "../data/account";
import { seed } from "../data/seed";
import type { Project, Task } from "../data/types";
import { fileType } from "../ui/helpers";
import { toast } from "../ui/toast";

const here = () => routeOf(location.pathname);

/* ---------- undo ---------- */
export const snapshot = () => JSON.stringify(S.data);
export function restore(snap: string) {
  S.data = JSON.parse(snap);
  save();
  render();
  resynced(); // a real workspace sends what the undo changed (an archive, a star, a checklist)
}

/* ---------- modals ---------- */
export function openModal(m: Modal) {
  S.ui.modals.push(m);
  S.ui.pop = null;
  render();
}
export function closeModal() {
  S.ui.modals.pop();
  render();
}
export interface ConfirmOpts {
  title: string;
  body: string; // may hold <b> (Gr8r's wording); rendered as HTML from our own strings only
  ok: string;
  danger?: boolean;
  icon?: string;
  typeName?: string;
  run: () => void;
}
export function confirmDlg(o: ConfirmOpts) {
  openModal({ type: "confirm", ...o });
}
export function promptDlg(o: { title: string; label: string; value: string; run: (v: string) => void }) {
  openModal({ type: "prompt", ...o });
}

/* ---------- create ---------- */
/** The project you're looking at (a project page, or the open task's). */
export function curProjectId(): string | null {
  const r = here();
  if (r.route === "project") return D().projects.find((p) => p.key.toLowerCase() === r.params.id?.toLowerCase())?.id ?? null;
  return null;
}
export function newTask(d: { project?: string; assignee?: string; due?: string; status?: Task["status"] } = {}) {
  const pid =
    d.project || curProjectId() || (S.ui.drawer && task(S.ui.drawer)?.project) || visibleProjects().find((p) => canSee(p) && p.status !== "complete")?.id;
  openModal({
    type: "task",
    form: {
      title: "",
      desc: "",
      project: canSee(proj(pid)) ? pid : visibleProjects().find(canSee)?.id,
      status: d.status || "todo",
      assignee: d.assignee || D().me,
      priority: "medium",
      due: d.due || null,
      start: null,
      labels: [],
      subtasks: [],
      files: [],
      recur: null,
      type: "task",
    },
  });
}
export function editTask(id: string) {
  const t = task(id);
  if (!t) return;
  openModal({
    type: "task",
    edit: t.id,
    form: {
      title: t.title,
      desc: (t.desc || "")
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim(),
      project: t.project,
      status: t.status,
      assignee: t.assignee,
      priority: t.priority,
      due: t.due,
      start: t.start,
      labels: [...t.labels],
      subtasks: t.subtasks.map((s) => ({ ...s })),
      files: [],
      recur: t.recur,
      type: t.type,
    },
  });
}
export const TEMPLATES = [
  { id: "blank", name: "Blank project", icon: "file", desc: "Start from scratch", tasks: [] as string[] },
  {
    id: "product",
    name: "Product Development",
    icon: "target",
    desc: "Discovery to launch",
    tasks: ["Define problem statement", "User research plan", "Write PRD", "Design exploration", "Build MVP", "Beta launch"],
  },
  {
    id: "web",
    name: "Website",
    icon: "globe",
    desc: "IA, design, build, launch",
    tasks: ["Sitemap & information architecture", "Wireframes", "Visual design", "Build page templates", "Content migration", "QA & launch"],
  },
  {
    id: "mkt",
    name: "Marketing Campaign",
    icon: "megaphone",
    desc: "Brief, assets, channels",
    tasks: ["Campaign brief", "Audience research", "Creative assets", "Channel plan", "Launch campaign", "Performance report"],
  },
  {
    id: "design",
    name: "Design Project",
    icon: "palette",
    desc: "Discovery to handoff",
    tasks: ["Discovery workshop", "Moodboard", "Concept directions", "Refinement", "Developer handoff"],
  },
  {
    id: "software",
    name: "Software Development",
    icon: "code",
    desc: "Spec, build, ship",
    tasks: ["Technical spec", "Set up repo & CI", "Implement core API", "Write tests", "Code review", "Deploy to staging"],
  },
  {
    id: "personal",
    name: "Personal Project",
    icon: "heart",
    desc: "Plan your own goals",
    tasks: ["Brain dump ideas", "Pick top 3 priorities", "Schedule focus time", "Weekly review"],
  },
];
export function makeKey(name: string) {
  const base =
    name
      .split(/\s+/)
      .filter(Boolean)
      .map((w) => w[0])
      .join("")
      .toUpperCase()
      .replace(/[^A-Z]/g, "")
      .slice(0, 4) || "PRJ";
  let key = base;
  let n = 2;
  while (D().projects.some((p) => p.key === key)) key = base + n++;
  return key;
}
export function createProject(
  f: { name: string; desc?: string; icon: string; color: string; team: string; lead: string; due?: string },
  tmplId: string,
): Project {
  const p: Project = {
    id: uid("p"),
    key: makeKey(f.name),
    name: f.name,
    icon: f.icon,
    color: f.color,
    status: "planning",
    team: f.team,
    lead: f.lead,
    due: f.due || dOff(30),
    start: dOff(0),
    fav: false,
    members: [...new Set([D().me, f.lead])],
    desc: f.desc || "No description yet.",
    milestones: [],
    last: 0,
  };
  D().projects.push(p);
  D().projOrder.unshift(p.id);
  D().activity.unshift({ id: uid("a"), by: D().me, verb: "created project", task: null, project: p.id, at: Date.now(), extra: "" });
  const tm = TEMPLATES.find((t) => t.id === tmplId);
  (tm?.tasks || []).forEach((title, i) => createTask({ project: p.id, title, status: i ? "todo" : "progress" }));
  projectCreated(p);
  return p;
}
export function newProject() {
  if (!allowed("projects:manage")) return;
  openModal({ type: "project", form: { name: "", desc: "", icon: "folder", color: "indigo", team: me().team, lead: D().me, due: dOff(30), tmpl: "blank" } });
}
export function editProject(id: string) {
  const p = proj(id)!;
  openModal({
    type: "project",
    edit: p.id,
    form: { name: p.name, desc: p.desc, icon: p.icon, color: p.color, team: p.team, lead: p.lead, due: p.due, tmpl: "blank" },
  });
}
export function share(id: string) {
  openModal({ type: "share", id });
}
export function invite() {
  if (!canInvite()) return; // (a shortcut or an old link; the control itself isn't shown)
  openModal({ type: "invite" });
}
export function newTeam() {
  if (!allowed("members:manage")) return;
  openModal({ type: "team", form: { name: "", desc: "", icon: "users", color: "teal", members: [] as string[] } });
}
export function editTeam(id: string) {
  const t = team(id);
  if (!t) return;
  openModal({
    type: "team",
    edit: t.id,
    form: {
      name: t.name,
      desc: t.desc,
      icon: t.icon,
      color: Object.keys(PCOLORS).find((k) => PCOLORS[k] === t.c) || "slate",
      members: D()
        .members.filter((m) => m.team === t.id)
        .map((m) => m.id),
    },
  });
}

/* ---------- tasks ---------- */
/** Remove issues from the store; a real workspace deletes them on the API too (`send: false` when
 * something else deletes them there, like their project). */
export function deleteTasks(ids: string[], { send = true } = {}) {
  const set = new Set(ids);
  if (send) tasksDeleted(D().tasks.filter((t) => set.has(t.id)));
  D().tasks = D().tasks.filter((t) => !set.has(t.id));
  D().tasks.forEach((t) => (t.deps = t.deps.filter((d) => !set.has(d))));
  D().comments = D().comments.filter((c) => !set.has(c.task));
  if (S.ui.drawer && set.has(S.ui.drawer)) S.ui.drawer = null;
  ids.forEach((i) => S.ui.sel.delete(i));
}
export function dupTask(id: string) {
  const t = task(id)!;
  S.ui.pop = null;
  let n: Task | undefined;
  mutate(() => {
    n = createTask({ ...JSON.parse(JSON.stringify(t)), id: uid("t"), key: undefined, title: t.title + " (copy)", created: Date.now(), fav: false });
    n.key = nextKey(proj(n.project)!);
  });
  toast("Task duplicated", { action: "Open", onAction: () => openTask(n!.id) });
}
/** Something a real workspace can't do yet: it says so instead. */
export function notYet(what: string, instead = "Mark the issue done instead.") {
  if (!isLive()) return false;
  S.ui.pop = null;
  toast(`${what} isn't available yet.${instead ? ` ${instead}` : ""}`, { kind: "info" });
  return true;
}
export function archiveTask(id: string) {
  const t = task(id)!;
  const snap = snapshot();
  S.ui.pop = null;
  if (S.ui.drawer === t.id) S.ui.drawer = null;
  mutate(() => {
    t.archived = true;
    logAct("archived", t);
  });
  toast(`Archived “${t.title}”`, { action: "Undo", onAction: () => restore(snap) });
}
export function delTask(id: string) {
  const t = task(id);
  S.ui.pop = null;
  if (!t) return;
  const n = commentsOf(t.id).length;
  const undoable = !isLive(); // a real workspace's delete is for good
  confirmDlg({
    title: "Delete task?",
    body: `<b>${escapeHtml(t.title)}</b>${t.subtasks.length ? `, its ${t.subtasks.length} subtasks,` : ""} and ${n} comment${n === 1 ? "" : "s"} will be permanently deleted.`,
    ok: "Delete task",
    danger: true,
    run: () => {
      const snap = snapshot();
      if (guarded(() => deleteTasks([t.id]))) toast(`Deleted “${t.title}”`, undoable ? { action: "Undo", onAction: () => restore(snap) } : {});
    },
  });
}

/* ---------- projects ---------- */
export function dupProject(id: string) {
  const p = proj(id)!;
  S.ui.pop = null;
  let n: Project | undefined;
  mutate(() => {
    n = createProject({ ...p, name: p.name + " copy" }, "blank");
    tasksOf(p.id).forEach((t) => createTask({ ...JSON.parse(JSON.stringify(t)), id: uid("t"), key: undefined, project: n!.id, status: "todo" }));
  });
  toast(`Duplicated ${p.name}`, { action: "Open", onAction: () => go("project", { id: n!.key }) });
}
export function archiveProject(id: string) {
  const p = proj(id)!;
  S.ui.pop = null;
  confirmDlg({
    title: `Archive ${p.name}?`,
    body: "The project will be hidden from the sidebar and project lists. Tasks, files, and comments are kept, and you can restore it from Archive.",
    ok: "Archive project",
    icon: "archive",
    run: () => {
      const snap = snapshot();
      if (guarded(() => (p.archived = true))) {
        if (here().route === "project") go("projects");
        toast(`Archived ${p.name}`, { action: "Undo", onAction: () => restore(snap) });
      }
    },
  });
}
export function delProject(id: string) {
  const p = proj(id)!;
  S.ui.pop = null;
  const n = tasksOf(p.id).length;
  confirmDlg({
    title: `Delete ${p.name}?`,
    body: `This permanently deletes the project and its <b>${n} task${n === 1 ? "" : "s"}</b>, files, and comments for everyone. This can't be undone.`,
    ok: "Delete project",
    danger: true,
    typeName: p.name,
    run: () => {
      const snap = snapshot();
      if (
        guarded(() => {
          // Deleting the project deletes its issues on the API: none are sent one by one.
          deleteTasks(
            D()
              .tasks.filter((t) => t.project === p.id)
              .map((t) => t.id),
            { send: false },
          );
          D().projects = D().projects.filter((x) => x !== p);
          D().projOrder = D().projOrder.filter((x) => x !== p.id);
          D().files = D().files.filter((f) => f.project !== p.id);
        })
      ) {
        if (here().route === "project") go("projects");
        if (isLive()) {
          projectDeleted(p);
          toast(`Deleted ${p.name}`);
        } else toast(`Deleted ${p.name}`, { action: "Undo", onAction: () => restore(snap) });
      }
    },
  });
}

/* ---------- board columns (a view key: "p:<project id>", "sv:<view id>", or a page) ---------- */
export function projectFromKey(key: string | undefined): string | null {
  if (!key) return null;
  if (key.startsWith("p:")) return key.slice(2);
  if (key.startsWith("sv:")) return D().savedViews.find((v) => v.id === key.slice(3))?.project ?? null;
  return null;
}
export function colTasks(key: string, st: string) {
  const pid = projectFromKey(key);
  return (pid ? tasksOf(pid) : allTasks()).filter((t) => t.status === st);
}
export function startComposer(key: string, group: string, gb: Partial<Task>) {
  S.ui.composer = { key, group, gb } as typeof S.ui.composer & { gb: Partial<Task> };
  S.ui.pop = null;
  render();
}
export function cancelComposer() {
  S.ui.composer = null;
  render();
}
export function commitComposer(title: string) {
  const c = S.ui.composer as (typeof S.ui.composer & { gb?: Partial<Task> }) | null;
  if (!c) return;
  const v = title.trim();
  if (!v) return cancelComposer();
  const f: Partial<Task> = { title: v, ...(c.gb ?? {}) };
  f.project = f.project || projectFromKey(c.key) || curProjectId() || "p1";
  if (c.key === "mytasks") f.assignee = D().me;
  guarded(() => {
    createTask(f);
  });
}
export function colAdd(key: string, st: string) {
  const pid = projectFromKey(key);
  startComposer(key, st, { status: st as Task["status"], ...(pid ? { project: pid } : {}) });
}
export function colCollapse(key: string, st: string) {
  S.ui.collapsedCols[key + ":" + st] = true;
  S.ui.pop = null;
  render();
}
export function colDoneAll(key: string, st: string) {
  const ts = colTasks(key, st);
  S.ui.pop = null;
  if (!ts.length) return render();
  const snap = snapshot();
  if (guarded(() => ts.forEach((t) => applyPatch(t, { status: "done" }))))
    toast(`Marked ${ts.length} tasks as done`, { action: "Undo", onAction: () => restore(snap) });
}
export function colArchive(key: string) {
  const ts = colTasks(key, "done");
  S.ui.pop = null;
  const snap = snapshot();
  if (guarded(() => ts.forEach((t) => (t.archived = true)))) toast(`Archived ${ts.length} completed tasks`, { action: "Undo", onAction: () => restore(snap) });
}
export function colSortPrio(key: string, st: string) {
  const ts = colTasks(key, st).sort((a, b) => PR[b.priority].w - PR[a.priority].w);
  const base = Math.min(...ts.map((t) => t.order));
  S.ui.pop = null;
  mutate(() => ts.forEach((t, i) => (t.order = base + i * 0.001)));
}

/* ---------- members ---------- */
export function copyEmail(id: string) {
  closePop();
  void copy(mem(id)!.email, "Email copied");
}
const errOf = (e: unknown) => (e instanceof Error && e.message ? e.message : "try again");
export function resendInvite(id: string) {
  closePop();
  const m = mem(id)!;
  if (!isLive()) return toast(`Invite resent to ${m.email}`);
  void inviteResent(m)
    .then(() => toast(`Invite resent to ${m.email}`))
    .catch((e: unknown) => toast(`The invite wasn't resent: ${errOf(e)}`, { kind: "err" }));
}
/** Hand a workspace to another member (its owner only); you become an admin. */
export function transferOwnership(id: string) {
  const m = mem(id)!;
  S.ui.pop = null;
  confirmDlg({
    title: `Make ${m.name} the owner?`,
    body: `${escapeHtml(m.name)} becomes the owner of ${escapeHtml(D().ws.name)}, and you become an admin. Only they can hand it back.`,
    ok: "Transfer ownership",
    danger: true,
    icon: "crown",
    run: () => {
      if (!isLive()) {
        mutate(() => {
          me()!.role = "Admin";
          m.role = "Owner";
        });
        toast(`${m.name} owns the workspace now`);
        return;
      }
      void ownershipTransferred(m)
        .then(() => toast(`${m.name} owns the workspace now`))
        .catch((e: unknown) => toast(`Ownership didn't move: ${errOf(e)}`, { kind: "err" }));
    },
  });
}
export function removeMember(id: string) {
  const m = mem(id)!;
  S.ui.pop = null;
  const n = allTasks().filter((t) => t.assignee === m.id && t.status !== "done").length;
  const pending = isInvite(m.id);
  confirmDlg({
    title: pending ? `Revoke the invite to ${m.email}?` : `Remove ${m.name}?`,
    body: pending
      ? "The link in their email stops working."
      : `${escapeHtml(m.name)} will lose access to ${escapeHtml(D().ws.name)} immediately.${n ? ` Their <b>${n} open task${n > 1 ? "s" : ""}</b> will become unassigned.` : ""}`,
    ok: pending ? "Revoke invite" : "Remove member",
    danger: true,
    icon: "user-minus",
    run: () => {
      if (isLive()) {
        // Permanent on the API: no undo. The store follows once it's done.
        void memberRemoved(m)
          .then(() => {
            mutate(() => {
              D().members = D().members.filter((x) => x.id !== m.id);
              D().tasks.forEach((t) => t.assignee === m.id && (t.assignee = null));
              D().projects.forEach((p) => (p.members = p.members.filter((x) => x !== m.id)));
            });
            if (here().route === "member") go("members");
            toast(pending ? `Revoked the invite to ${m.email}` : `Removed ${m.name}`);
          })
          .catch((e: unknown) => toast(`${m.name} wasn't removed: ${errOf(e)}`, { kind: "err", ms: 6000 }));
        return;
      }
      const snap = snapshot();
      if (
        guarded(() => {
          D().members = D().members.filter((x) => x !== m);
          D().tasks.forEach((t) => {
            if (t.assignee === m.id) t.assignee = null;
          });
          D().projects.forEach((p) => (p.members = p.members.filter((x) => x !== m.id)));
        })
      ) {
        if (here().route === "member") go("members");
        toast(`Removed ${m.name}`, { action: "Undo", onAction: () => restore(snap) });
      }
    },
  });
}

/* ---------- files ---------- */
export function previewFile(id: string) {
  const f = D().files.find((x) => x.id === id);
  S.ui.pop = null;
  if (f) openModal({ type: "filePreview", file: f, tid: f.task });
}
export function renameFile(id: string) {
  const f = D().files.find((x) => x.id === id)!;
  S.ui.pop = null;
  promptDlg({
    title: "Rename file",
    label: "File name",
    value: f.name,
    run: (v) => {
      if (!v || v === f.name) return;
      const was = f.name;
      mutate(() => {
        f.name = v;
        f.type = fileType(v);
      });
      fileRenamed(f, was);
    },
  });
}
export function dupFile(id: string) {
  const f = D().files.find((x) => x.id === id)!;
  S.ui.pop = null;
  if (isLive()) {
    void fileDuplicated(f);
    return;
  }
  mutate(() => {
    const i = D().files.indexOf(f);
    D().files.splice(i + 1, 0, { ...f, id: uid("f"), name: f.name.replace(/(\.[^.]+)$/, " copy$1"), at: Date.now(), by: D().me });
  });
  toast("File duplicated");
}
export function delFile(id: string) {
  const f = D().files.find((x) => x.id === id)!;
  S.ui.pop = null;
  confirmDlg({
    title: "Delete file?",
    body: isLive()
      ? `<b>${escapeHtml(f.name)}</b> will be deleted, with its converted copy in Knowledge (that one can be restored from its history).`
      : `<b>${escapeHtml(f.name)}</b> will be removed from the project${f.task ? " and its task" : ""}.`,
    ok: "Delete file",
    danger: true,
    run: () => {
      if (isLive()) {
        mutate(() => (D().files = D().files.filter((x) => x !== f)));
        fileDeleted(f);
        toast(`Deleted ${f.name}`);
        return;
      }
      const snap = snapshot();
      if (
        guarded(() => {
          D().files = D().files.filter((x) => x !== f);
          const t = f.task ? task(f.task) : undefined;
          if (t) t.attachments = t.attachments.filter((a) => a.name !== f.name);
        })
      )
        toast(`Deleted ${f.name}`, { action: "Undo", onAction: () => restore(snap) });
    },
  });
}

/* ---------- saved views ---------- */
export function renameView(id: string) {
  const v = D().savedViews.find((x) => x.id === id)!;
  S.ui.pop = null;
  promptDlg({
    title: "Rename view",
    label: "View name",
    value: v.name,
    run: (val) => {
      if (val) mutate(() => (v.name = val));
    },
  });
}
export function delView(id: string) {
  const v = D().savedViews.find((x) => x.id === id)!;
  S.ui.pop = null;
  mutate(() => (D().savedViews = D().savedViews.filter((x) => x !== v)));
  const r = here();
  if (r.route === "project" && r.params.tab === "v:" + v.id) go("project", { id: proj(v.project)!.key, tab: "list" });
  toast(`Deleted view “${v.name}”`);
}

/* ---------- workspace, account, help ---------- */
export function switchWs(id: string) {
  const w = D().workspaces.find((x) => x.id === id)!;
  S.ui.pop = null;
  if (w.slug) {
    location.assign(`/w/${w.slug}`); // a real workspace: load it from the API
    return;
  }
  D().ws = { ...w, url: w.name.toLowerCase().replace(/[^a-z0-9]+/g, ""), brand: Boolean(w.brand) };
  save();
  go("home");
  toast(`Switched to ${w.name}`);
}
export function signOut() {
  S.ui.pop = null;
  S.ui.palette = null;
  S.ui.drawer = null;
  S.ui.modals = [];
  render();
  showDemo();
  void signOutLive(); // ends the session (if any), then the sign-in page
}
export function shortcuts() {
  S.ui.pop = null;
  S.ui.palette = null;
  openModal({ type: "shortcuts" });
}
export function resetDemo() {
  S.ui.pop = null;
  confirmDlg({
    title: "Reset demo data?",
    body: "All projects, tasks, and settings in this browser go back to the original sample workspace.",
    ok: "Reset data",
    danger: true,
    icon: "rotate-ccw",
    run: () => {
      S.data = seed();
      S.views = {};
      S.prefs = { ...DEFAULT_PREFS, theme: S.prefs.theme };
      S.ui.drawer = null;
      save();
      go("home");
      toast("Demo data restored");
    },
  });
}
export function toggleOffline() {
  S.ui.offline = !S.ui.offline;
  S.ui.pop = null;
  render();
  toast(S.ui.offline ? "Offline mode on — edits will fail to save" : "Back online", { kind: S.ui.offline ? "err" : undefined });
}

export function escapeHtml(s: string) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}
