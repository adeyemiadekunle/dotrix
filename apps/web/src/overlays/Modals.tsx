// Gr8r's modals (gr8r-studio/src/overlays/modals.js and features/teams.js), same markup. Each
// open modal is an entry in S.ui.modals; its form lives on the entry.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { applyPatch, copy, createTask, openPop, openTask } from "../core/actions";
import { PCOLORS, PICONS } from "../core/constants";
import { Ic } from "../core/icons";
import { closeModal, createProject, escapeHtml, newTask, restore, snapshot, TEMPLATES } from "../core/more";
import { currentSlug, go } from "../core/nav";
import { MOD, ago, fmtDate, uid } from "../core/utils";
import { filesAttached, isLive, projectChanged } from "../data/live";
import { D, S, TM, mem, mutate, pColor, proj, render, task, tasksOf, team, teamsList, type Modal } from "../data/store";
import type { FileItem, Task } from "../data/types";
import { Av, FT, FilePrev, Lbl, PrPill, StPill, fileType, fsize } from "../ui/helpers";
import { toast } from "../ui/toast";
import { viewOf } from "../shell/viewEngine";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const top = () => S.ui.modals[S.ui.modals.length - 1]!;

export function ModalLayer() {
  return (
    <>
      {S.ui.modals.map((m, i) => (
        <div key={i}>
          <div className="scrim enter" onClick={closeModal} style={{ zIndex: 60 + i * 2 }} />
          <div
            className="modal-wrap"
            style={{ zIndex: 61 + i * 2 }}
            onMouseDown={(e) => e.target === e.currentTarget && closeModal()}
            onKeyDown={(e) => {
              if (e.key === "Escape") closeModal();
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) (e.currentTarget.querySelector("[data-submit]") as HTMLButtonElement | null)?.click();
            }}
          >
            <ModalBody m={m} />
          </div>
        </div>
      ))}
    </>
  );
}

function H({ title, sub, id }: { title: ReactNode; sub?: ReactNode; id: string }) {
  return (
    <div className="modal-h">
      <div>
        <h2 id={`mt-${id}`}>{title}</h2>
        {sub && (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      <button className="ibtn ibtn-sm" onClick={closeModal} aria-label="Close">
        <Ic n="x" s={16} />
      </button>
    </div>
  );
}
function Wrap({ cls = "", m, children }: { cls?: string; m: Modal; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    (el?.querySelector<HTMLElement>("[autofocus]") ?? el?.querySelector<HTMLElement>("input,textarea,button"))?.focus();
  }, []);
  return (
    <div ref={ref} className={`modal enter ${cls}`} role="dialog" aria-modal="true" aria-labelledby={`mt-${m.type}`}>
      {children}
    </div>
  );
}

function ModalBody({ m }: { m: Modal }) {
  switch (m.type) {
    case "task":
      return (
        <Wrap m={m}>
          <TaskModal m={m} />
        </Wrap>
      );
    case "project":
      return (
        <Wrap m={m}>
          <ProjectModal m={m} />
        </Wrap>
      );
    case "share":
      return (
        <Wrap m={m}>
          <ShareModal m={m} />
        </Wrap>
      );
    case "invite":
      return (
        <Wrap m={m}>
          <InviteModal />
        </Wrap>
      );
    case "confirm":
      return (
        <Wrap m={m} cls="sm">
          <ConfirmModal m={m} />
        </Wrap>
      );
    case "prompt":
      return (
        <Wrap m={m} cls="sm">
          <PromptModal m={m} />
        </Wrap>
      );
    case "shortcuts":
      return (
        <Wrap m={m} cls="lg">
          <ShortcutsModal />
        </Wrap>
      );
    case "team":
      return (
        <Wrap m={m}>
          <TeamModal m={m} />
        </Wrap>
      );
    case "filePreview":
      return (
        <Wrap m={m} cls="lg">
          <FilePreviewModal m={m} />
        </Wrap>
      );
    case "saveView":
      return (
        <Wrap m={m} cls="sm">
          <SaveViewModal m={m} />
        </Wrap>
      );
  }
  return null;
}

/* ---------- task ---------- */
type TaskForm = {
  title: string;
  desc: string;
  project: string;
  status: Task["status"];
  assignee: string | null;
  priority: Task["priority"];
  due: string | null;
  start: string | null;
  labels: string[];
  subtasks: Task["subtasks"];
  /** `file` is kept so a real workspace can upload it once the issue exists. */
  files: { name: string; size: string; type: string; file?: File }[];
  recur: string | null;
  type: Task["type"];
  more?: boolean;
};
function FormChip({ pop, label, field, children }: { pop: string; label: string; field?: string; children: ReactNode }) {
  return (
    <button type="button" className="pillbtn bordered" onClick={(e) => openPop(e.currentTarget, pop, { id: "__form", field })} aria-label={label}>
      {children}
    </button>
  );
}
/** The files picked in the form that can be uploaded (not just named). */
const picked = (files: TaskForm["files"]) => files.flatMap((x) => (x.file ? [x.file] : []));
function TaskModal({ m }: { m: Modal }) {
  const f = m.form as TaskForm;
  const err = m.err as string | undefined;
  const p = proj(f.project);
  const set = (k: keyof TaskForm, v: unknown) => {
    (f as Record<string, unknown>)[k] = v;
    if (k === "title" && m.err && String(v).trim()) m.err = undefined;
    render();
  };
  const submit = () => {
    const title = f.title.trim();
    if (!title) {
      m.err = "Give the task a name";
      return render();
    }
    m.err = undefined;
    const files = f.files.map((x) => ({ id: uid("a"), name: x.name, type: x.type, size: x.size, by: D().me, at: Date.now() }));
    const base: Partial<Task> = {
      title,
      project: f.project,
      status: f.status,
      assignee: f.assignee,
      priority: f.priority,
      due: f.due,
      start: f.start && f.due && f.start > f.due ? f.due : f.start,
      labels: f.labels,
      recur: f.recur,
      subtasks: f.subtasks,
      type: f.type,
    };
    if (m.edit) {
      const t = task(m.edit as string)!;
      mutate(() => {
        const descChanged = f.desc !== (t.desc || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
        applyPatch(t, descChanged ? { ...base, desc: f.desc ? `<p>${escapeHtml(f.desc)}</p>` : "" } : base);
        if (!isLive()) t.attachments.push(...files);
      });
      if (isLive()) filesAttached(t, picked(f.files));
      closeModal();
      toast("Changes saved");
      return;
    }
    let t: Task | undefined;
    mutate(() => {
      t = createTask({ ...base, desc: f.desc ? `<p>${escapeHtml(f.desc)}</p>` : "", attachments: isLive() ? [] : files });
      if (!isLive()) files.forEach((x) => D().files.unshift({ ...x, project: t!.project, task: t!.id } as FileItem));
    });
    if (isLive()) filesAttached(t!, picked(f.files));
    if (f.more) {
      Object.assign(f, { title: "", desc: "", subtasks: [], files: [] });
      render();
      toast(`Created ${t!.key}`, { ms: 2000 });
      return;
    }
    closeModal();
    toast(`Created ${t!.key} in ${proj(t!.project)!.name}`, { action: "Open", onAction: () => openTask(t!.id) });
  };
  const [sub, setSub] = useState("");
  return (
    <>
      <H id="task" title={m.edit ? "Edit task" : "New task"} sub={m.edit ? <span className="mono">{task(m.edit as string)?.key}</span> : undefined} />
      <form
        className="modal-b"
        style={{ gap: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="field">
          <label className="sr" htmlFor="f-title">
            Task name
          </label>
          <input
            className={`input input-lg ${err ? "is-error" : ""}`}
            id="f-title"
            value={f.title}
            onChange={(e) => set("title", e.target.value)}
            placeholder="Task name"
            autoFocus
            aria-invalid={Boolean(err)}
            style={{ fontSize: 15, fontWeight: 500 }}
          />
          {err && (
            <span className="err">
              <Ic n="circle-alert" s={12} />
              {err}
            </span>
          )}
        </div>
        <div className="field">
          <label className="sr" htmlFor="f-desc">
            Description
          </label>
          <textarea className="textarea" id="f-desc" value={f.desc} onChange={(e) => set("desc", e.target.value)} placeholder="Add a description… (optional)" rows={3} />
        </div>
        <div className="row" style={{ flexWrap: "wrap", gap: 6 }}>
          <FormChip pop="project" label="Project">
            <span className="pdot" style={css({ "--c": pColor(p) })} />
            {p?.name || "Project"}
          </FormChip>
          <FormChip pop="status" label="Status">
            <StPill st={f.status} />
          </FormChip>
          <FormChip pop="assignee" label="Assignee">
            <Av id={f.assignee} cls="sm" tip={false} />
            {mem(f.assignee)?.name || "Assignee"}
          </FormChip>
          <FormChip pop="priority" label="Priority">
            <PrPill p={f.priority} />
          </FormChip>
          <FormChip pop="date" label="Due date" field="due">
            <Ic n="calendar" s={13} />
            {f.due ? "Due " + fmtDate(f.due) : "Due date"}
          </FormChip>
          <FormChip pop="date" label="Start date" field="start">
            <Ic n="calendar-arrow-up" s={13} />
            {f.start ? "Starts " + fmtDate(f.start) : "Start date"}
          </FormChip>
          <FormChip pop="labels" label="Labels">
            {f.labels.length ? (
              f.labels.map((l) => <Lbl key={l} id={l} />)
            ) : (
              <>
                <Ic n="tag" s={13} />
                Labels
              </>
            )}
          </FormChip>
          <FormChip pop="recur" label="Repeat">
            <Ic n="repeat" s={13} />
            {f.recur || "Repeat"}
          </FormChip>
        </div>
        <div className="field">
          <span className="label">Subtasks</span>
          {f.subtasks.map((s, i) => (
            <div key={s.id} className="subt" style={{ padding: "0 4px" }}>
              <Ic n="circle" s={13} />
              <span className="s">{s.title}</span>
              <button type="button" className="ibtn ibtn-xs x" style={{ opacity: 1 }} onClick={() => (f.subtasks.splice(i, 1), render())} aria-label="Remove">
                <Ic n="x" s={12} />
              </button>
            </div>
          ))}
          <div className="inwrap">
            <Ic n="plus" s={14} />
            <input
              className="input"
              id="f-sub"
              value={sub}
              onChange={(e) => setSub(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (sub.trim()) {
                    f.subtasks.push({ id: uid("s"), title: sub.trim(), done: false });
                    setSub("");
                    render();
                  }
                }
              }}
              placeholder="Add a subtask and press Enter"
            />
          </div>
        </div>
        <div className="field">
          <span className="label">Attachments</span>
          {f.files.length > 0 && (
            <div className="col" style={{ gap: 4 }}>
              {f.files.map((x, i) => (
                <div key={i} className="upl" style={{ padding: "6px 10px" }}>
                  <span className="ftype" style={css({ "--c": FT[x.type]!.c, width: 22, height: 22 })}>
                    <Ic n={FT[x.type]!.i} s={12} />
                  </span>
                  <span className="grow trunc">{x.name}</span>
                  <span className="faint" style={{ fontSize: 11.5 }}>
                    {x.size}
                  </span>
                  <button type="button" className="ibtn ibtn-xs" onClick={() => (f.files.splice(i, 1), render())} aria-label="Remove">
                    <Ic n="x" s={12} />
                  </button>
                </div>
              ))}
            </div>
          )}
          <label className="dropzone" style={{ padding: 10 }}>
            <Ic n="paperclip" s={14} />
            <span>Attach files</span>
            <input
              type="file"
              multiple
              hidden
              onChange={(e) => {
                [...(e.target.files ?? [])].forEach((x) => f.files.push({ name: x.name, size: fsize(x.size), type: fileType(x.name), file: x }));
                render();
              }}
            />
          </label>
        </div>
      </form>
      <div className="modal-f">
        {!m.edit && (
          <label className="row" style={{ gap: 8, fontSize: 12.5, color: "var(--text-2)", cursor: "pointer" }}>
            <input type="checkbox" className="toggle" id="f-more" checked={Boolean(f.more)} onChange={(e) => set("more", e.target.checked)} />
            Create more
          </label>
        )}
        <span className="sp" />
        <span className="faint hide-m" style={{ fontSize: 11.5 }}>
          <kbd>{MOD}</kbd> <kbd>↵</kbd>
        </span>
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={submit}>
          {m.edit ? "Save changes" : "Create task"}
        </button>
      </div>
    </>
  );
}
/** The new-task form, for popovers editing it ("__form"). */
export function taskForm(): TaskForm | null {
  const m = [...S.ui.modals].reverse().find((x) => x.type === "task");
  return (m?.form as TaskForm) ?? null;
}

/* ---------- project ---------- */
type ProjectForm = { name: string; desc: string; icon: string; color: string; team: string; lead: string; due: string; tmpl: string };
function ProjectModal({ m }: { m: Modal }) {
  const f = m.form as ProjectForm;
  const err = m.err as string | undefined;
  const set = (k: keyof ProjectForm, v: string) => {
    f[k] = v;
    if (k === "name" && m.err && v.trim()) m.err = undefined;
    render();
  };
  const submit = () => {
    f.name = f.name.trim();
    if (!f.name) {
      m.err = "Give the project a name";
      return render();
    }
    if (m.edit) {
      const p = proj(m.edit as string)!;
      mutate(() => Object.assign(p, { name: f.name, desc: f.desc, icon: f.icon, color: f.color, team: f.team, lead: f.lead, due: f.due, members: [...new Set([...p.members, f.lead])] }));
      projectChanged(p, ["name", "desc", "icon", "color", "due"]);
      closeModal();
      toast("Project updated");
      return;
    }
    let p: ReturnType<typeof createProject> | undefined;
    mutate(() => (p = createProject(f, f.tmpl)));
    closeModal();
    go("project", { id: p!.key, tab: f.tmpl === "blank" ? "overview" : "board" });
    const n = tasksOf(p!.id).length;
    toast(`Created ${p!.name}${n ? ` with ${n} starter tasks` : ""}`);
  };
  return (
    <>
      <H id="project" title={m.edit ? "Project settings" : "New project"} sub={m.edit ? undefined : "Projects hold tasks, files, and conversations for one body of work."} />
      <form
        className="modal-b"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
          <span className="picon lg" style={css({ "--c": PCOLORS[f.color]!, flexShrink: 0, marginTop: 22 })} aria-hidden="true">
            <Ic n={f.icon} s={18} />
          </span>
          <div className="field grow">
            <label className="label" htmlFor="p-name">
              Project name
            </label>
            <input className={`input ${err ? "is-error" : ""}`} id="p-name" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Website Redesign" autoFocus aria-invalid={Boolean(err)} />
            {err && (
              <span className="err">
                <Ic n="circle-alert" s={12} />
                {err}
              </span>
            )}
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="p-desc">
            Description
          </label>
          <textarea className="textarea" id="p-desc" rows={2} value={f.desc} onChange={(e) => set("desc", e.target.value)} placeholder="What is this project about?" />
        </div>
        <div className="row" style={{ gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div className="field" style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Icon</span>
            <div className="iconpick" role="radiogroup" aria-label="Icon">
              {PICONS.map((i) => (
                <button key={i} type="button" role="radio" aria-checked={f.icon === i} className={f.icon === i ? "on" : ""} onClick={() => set("icon", i)} aria-label={i}>
                  <Ic n={i} s={15} />
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span className="label">Color</span>
            <div className="swatches" role="radiogroup" aria-label="Color" style={{ maxWidth: 140 }}>
              {Object.entries(PCOLORS).map(([k, v]) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={f.color === k}
                  className={`sw ${f.color === k ? "on" : ""}`}
                  style={css({ "--c": v, width: 22, height: 22 })}
                  onClick={() => set("color", k)}
                  aria-label={k}
                >
                  {f.color === k && <Ic n="check" s={12} />}
                </button>
              ))}
            </div>
          </div>
        </div>
        <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
          <div className="field" style={{ flex: 1, minWidth: 150 }}>
            <label className="label" htmlFor="p-team">
              Team
            </label>
            <select className="select" id="p-team" value={f.team} onChange={(e) => set("team", e.target.value)}>
              {teamsList().map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 150 }}>
            <label className="label" htmlFor="p-lead">
              Lead
            </label>
            <select className="select" id="p-lead" value={f.lead} onChange={(e) => set("lead", e.target.value)}>
              {D()
                .members.filter((x) => x.status === "active")
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
            </select>
          </div>
          <div className="field" style={{ flex: 1, minWidth: 150 }}>
            <label className="label" htmlFor="p-due">
              Target date
            </label>
            <input type="date" className="input" id="p-due" value={f.due || ""} onChange={(e) => set("due", e.target.value)} />
          </div>
        </div>
        {!m.edit && (
          <div className="field">
            <span className="label">Template</span>
            <div className="tmpls" role="radiogroup">
              {TEMPLATES.map((t) => (
                <button key={t.id} type="button" role="radio" aria-checked={f.tmpl === t.id} className={`opt ${f.tmpl === t.id ? "on" : ""}`} onClick={() => set("tmpl", t.id)} style={{ padding: 10 }}>
                  <Ic n={t.icon} s={16} />
                  <b style={{ fontSize: 12.5 }}>{t.name}</b>
                  <span>{t.tasks.length ? t.tasks.length + " starter tasks" : t.desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </form>
      <div className="modal-f">
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={submit}>
          {m.edit ? "Save changes" : "Create project"}
        </button>
      </div>
    </>
  );
}

/* ---------- share ---------- */
export const PERMS = ["Can view", "Can comment", "Can edit", "Full access"];
function ShareModal({ m }: { m: Modal }) {
  const p = proj(m.id as string)! as ReturnType<typeof proj> & { perms?: Record<string, string>; access?: string };
  p.perms = p.perms || {};
  p.access = p.access || "workspace";
  const q = (m.q as string) || "";
  const [perm, setPerm] = useState("Can edit");
  const invite = () => {
    const v = q.trim();
    if (!v) return;
    const ex = D().members.find((x) => x.email.toLowerCase() === v.toLowerCase() || x.name.toLowerCase() === v.toLowerCase());
    if (ex) {
      if (!p.members.includes(ex.id))
        mutate(() => {
          p.members.push(ex.id);
          p.perms![ex.id] = perm;
        });
      m.q = "";
      render();
      toast(`Shared with ${ex.name}`);
      return;
    }
    if (!/^\S+@\S+\.\S+$/.test(v)) {
      toast("Enter a valid email address, like name@company.com", { kind: "err" });
      return;
    }
    const nm = v
      .split("@")[0]!
      .replace(/[._-]+/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
    mutate(() => {
      const id = uid("m");
      D().members.push({ id, name: nm, email: v, role: "Guest", team: p.team, title: "Guest", c: "#6B7280", status: "invited", last: null, tz: "—" });
      p.members.push(id);
      p.perms![id] = perm;
    });
    m.q = "";
    render();
    toast(`Invitation sent to ${v}`);
  };
  return (
    <>
      <H id="share" title={`Share “${p.name}”`} />
      <div className="modal-b">
        <form
          className="row"
          style={{ gap: 6 }}
          onSubmit={(e) => {
            e.preventDefault();
            invite();
          }}
        >
          <div className="grow">
            <label className="sr" htmlFor="share-in">
              Invite by email
            </label>
            <input className="input" id="share-in" placeholder="Add people by name or email" value={q} onChange={(e) => ((m.q = e.target.value), render())} autoFocus />
          </div>
          <select className="select" style={{ width: 132 }} aria-label="Permission" value={perm} onChange={(e) => setPerm(e.target.value)}>
            {PERMS.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <button className="btn btn-primary" type="submit">
            Invite
          </button>
        </form>
        {q && (
          <div className="panel" style={{ padding: 4 }}>
            {D()
              .members.filter((x) => !p.members.includes(x.id) && (x.name.toLowerCase().includes(q.toLowerCase()) || x.email.includes(q.toLowerCase())))
              .map((x) => (
                <button
                  key={x.id}
                  className="mi"
                  onClick={() => {
                    mutate(() => p.members.push(x.id));
                    m.q = "";
                    render();
                    toast(`${x.name} can now edit ${p.name}`);
                  }}
                >
                  <Av id={x.id} cls="sm" tip={false} />
                  {x.name}
                  <span className="r">{x.email}</span>
                </button>
              ))}
            {!D().members.some((x) => !p.members.includes(x.id) && (x.name.toLowerCase().includes(q.toLowerCase()) || x.email.includes(q.toLowerCase()))) && (
              <div className="mi faint" style={{ cursor: "default" }}>
                {q.includes("@") ? `Press Invite to send an invitation to ${q}` : "No matching members — enter an email to invite someone new"}
              </div>
            )}
          </div>
        )}
        <div>
          <div className="eyebrow" style={{ marginBottom: 4 }}>
            People with access
          </div>
          {p.members.map((id) => {
            const x = mem(id);
            if (!x) return null;
            const pm = id === p.lead ? "Full access" : p.perms![id] || (x.role === "Guest" ? "Can comment" : "Can edit");
            return (
              <div key={id} className="row" style={{ height: 44 }}>
                <Av id={id} cls="md" tip={false} />
                <div className="grow">
                  <div style={{ fontWeight: 500, fontSize: 13 }}>
                    {x.name}
                    {id === D().me && (
                      <span className="faint" style={{ fontWeight: 400 }}>
                        {" "}
                        (you)
                      </span>
                    )}
                  </div>
                  <div className="faint" style={{ fontSize: 11.5 }}>
                    {x.email}
                    {id === p.lead ? " · Project lead" : ""}
                  </div>
                </div>
                {id === p.lead ? (
                  <span className="muted" style={{ fontSize: 12.5, paddingRight: 8 }}>
                    Full access
                  </span>
                ) : (
                  <select
                    className="select"
                    style={{ width: "auto", height: 26, fontSize: 12, borderColor: "transparent", backgroundColor: "transparent" }}
                    value={pm}
                    aria-label={`Permission for ${x.name}`}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "__remove") {
                        const snap = snapshot();
                        mutate(() => (p.members = p.members.filter((y) => y !== id)));
                        toast(`Removed ${x.name}`, { action: "Undo", onAction: () => restore(snap) });
                      } else {
                        mutate(() => (p.perms![id] = v));
                        toast(`${x.name}: ${v}`, { ms: 1800 });
                      }
                    }}
                  >
                    {PERMS.map((qq) => (
                      <option key={qq}>{qq}</option>
                    ))}
                    <option value="__remove">Remove access</option>
                  </select>
                )}
              </div>
            );
          })}
        </div>
        <div style={{ borderTop: "1px solid var(--divider)", paddingTop: 12 }}>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            General access
          </div>
          <div className="row" style={{ gap: 10 }}>
            <span className="ftype" style={css({ "--c": "var(--text-2)" })}>
              <Ic n={p.access === "private" ? "lock" : "building-2"} s={14} />
            </span>
            <div className="grow">
              <select
                className="select"
                style={{ height: 28, width: "auto", borderColor: "transparent", paddingLeft: 4, fontWeight: 500 }}
                value={p.access}
                aria-label="General access"
                onChange={(e) =>
                  mutate(() => {
                    p.access = e.target.value;
                    p.private = e.target.value === "private";
                  })
                }
              >
                <option value="private">Only people invited</option>
                <option value="workspace">Everyone at {D().ws.name}</option>
              </select>
              <div className="faint" style={{ fontSize: 11.5, paddingLeft: 4 }}>
                {p.access === "private" ? "Only people listed above can open this project." : "Anyone in the workspace can view and comment."}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="modal-f">
        <button className="btn btn-secondary" onClick={() => void copy(`${location.origin}/w/${currentSlug()}/p/${p.key}/overview`)}>
          <Ic n="link" s={14} />
          Copy link
        </button>
        <span className="sp" />
        <button className="btn btn-primary" onClick={closeModal}>
          Done
        </button>
      </div>
    </>
  );
}

/* ---------- invite ---------- */
function InviteModal() {
  const m = top();
  const [emails, setEmails] = useState((m.draft as string) || "");
  const [role, setRole] = useState("Member");
  const [tm, setTm] = useState(teamsList()[0]?.id ?? "");
  const err = m.err as string | undefined;
  const submit = () => {
    const list = emails
      .split(/[\s,;]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const bad = list.filter((e) => !/^\S+@\S+\.\S+$/.test(e));
    if (!list.length) return ((m.err = "Enter at least one email address"), render());
    if (bad.length) return ((m.err = `${bad[0]} isn't a valid email address`), render());
    mutate(() =>
      list.forEach((e) => {
        if (!D().members.some((x) => x.email === e))
          D().members.push({
            id: uid("m"),
            name: e
              .split("@")[0]!
              .replace(/[._-]+/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase()),
            email: e,
            role: role as "Member",
            team: tm,
            title: role,
            c: "#6B7280",
            status: "invited",
            last: null,
            tz: "—",
          });
      }),
    );
    closeModal();
    toast(`${list.length} invitation${list.length > 1 ? "s" : ""} sent`);
  };
  return (
    <>
      <H id="invite" title={"Invite to " + D().ws.name} sub="Invited people get an email with a link to join." />
      <form
        className="modal-b"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="field">
          <label className="label" htmlFor="inv-emails">
            Email addresses
          </label>
          <textarea
            className={`textarea ${err ? "is-error" : ""}`}
            id="inv-emails"
            placeholder="name@company.com, another@company.com"
            rows={3}
            autoFocus
            value={emails}
            onChange={(e) => ((m.draft = e.target.value), setEmails(e.target.value))}
          />
          {err ? (
            <span className="err">
              <Ic n="circle-alert" s={12} />
              {err}
            </span>
          ) : (
            <span className="hint">Separate multiple addresses with commas.</span>
          )}
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div className="field grow">
            <label className="label" htmlFor="inv-role">
              Role
            </label>
            <select className="select" id="inv-role" value={role} onChange={(e) => setRole(e.target.value)}>
              {["Member", "Admin", "Guest"].map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
          <div className="field grow">
            <label className="label" htmlFor="inv-team">
              Team
            </label>
            <select className="select" id="inv-team" value={tm} onChange={(e) => setTm(e.target.value)}>
              {teamsList().map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="alert info">
          <Ic n="info" s={14} />
          <span>
            <b>Guests</b> can only see projects they&apos;re added to and can&apos;t create projects.
          </span>
        </div>
      </form>
      <div className="modal-f">
        <button className="btn btn-ghost" onClick={() => void copy(`${location.origin}/join/${D().ws.url}-7f3k2`, "Invite link copied")}>
          <Ic n="link" s={14} />
          Copy invite link
        </button>
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={submit}>
          Send invites
        </button>
      </div>
    </>
  );
}

/* ---------- confirm, prompt ---------- */
function ConfirmModal({ m }: { m: Modal }) {
  const [text, setText] = useState("");
  const needs = m.typeName as string | undefined;
  const ok = !needs || text === needs;
  const run = () => {
    if (!ok) return;
    closeModal();
    (m.run as () => void)?.();
  };
  return (
    <>
      <div className="modal-b" style={{ paddingTop: 18, gap: 10 }}>
        <div className="row" style={{ gap: 12, alignItems: "flex-start" }}>
          <span className="ftype" style={css({ "--c": m.danger ? "var(--red)" : "var(--amber)", width: 34, height: 34, borderRadius: 9 })}>
            <Ic n={(m.icon as string) || (m.danger ? "trash-2" : "archive")} s={17} />
          </span>
          <div className="grow">
            <h2 id="mt-confirm" style={{ fontSize: 15, fontWeight: 600, margin: "4px 0 6px" }}>
              {m.title as string}
            </h2>
            {/* Our own wording, with <b> for names (escaped where they come from data). */}
            <p className="muted" style={{ margin: 0, fontSize: 13, lineHeight: 1.55 }} dangerouslySetInnerHTML={{ __html: m.body as string }} />
          </div>
        </div>
        {needs && (
          <div className="field" style={{ marginTop: 6 }}>
            <label className="label" htmlFor="confirm-in" style={{ fontWeight: 400, color: "var(--text-2)" }}>
              Type <b style={{ color: "var(--text)", fontWeight: 600 }}>{needs}</b> to confirm
            </label>
            <input className="input" id="confirm-in" autoComplete="off" autoFocus value={text} onChange={(e) => setText(e.target.value)} />
          </div>
        )}
      </div>
      <div className="modal-f">
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal} autoFocus={!needs}>
          Cancel
        </button>
        <button className={`btn ${m.danger ? "btn-danger" : "btn-primary"}`} data-submit onClick={run} disabled={!ok}>
          {m.ok as string}
        </button>
      </div>
    </>
  );
}
function PromptModal({ m }: { m: Modal }) {
  const [v, setV] = useState((m.value as string) || "");
  const run = () => {
    closeModal();
    (m.run as (s: string) => void)(v.trim());
  };
  return (
    <>
      <H id="prompt" title={m.title as string} />
      <form
        className="modal-b"
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
      >
        <div className="field">
          <label className="label" htmlFor="prompt-in">
            {m.label as string}
          </label>
          <input className="input" id="prompt-in" value={v} onChange={(e) => setV(e.target.value)} autoFocus />
        </div>
      </form>
      <div className="modal-f">
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={run}>
          {(m.ok as string) || "Save"}
        </button>
      </div>
    </>
  );
}

/* ---------- shortcuts ---------- */
export const SHORTCUTS: [string, [string, string[]][]][] = [
  [
    "General",
    [
      ["Command menu", [MOD, "K"]],
      ["Search", ["/"]],
      ["Keyboard shortcuts", ["?"]],
      ["Toggle sidebar", ["["]],
      ["Toggle dark mode", [MOD, "Shift", "L"]],
      ["Close panel or dialog", ["Esc"]],
    ],
  ],
  [
    "Create",
    [
      ["New task", ["N"]],
      ["New project", ["P"]],
      ["Submit form", [MOD, "↵"]],
      ["Send comment", [MOD, "↵"]],
    ],
  ],
  [
    "Navigate",
    [
      ["Go to Home", ["G", "H"]],
      ["Go to My Tasks", ["G", "T"]],
      ["Go to Projects", ["G", "P"]],
      ["Go to Inbox", ["G", "I"]],
      ["Go to Calendar", ["G", "C"]],
      ["Go to Settings", ["G", "S"]],
    ],
  ],
  [
    "Command menu",
    [
      ["Move selection", ["↑", "↓"]],
      ["Run command", ["↵"]],
      ["Search mode", ["Tab"]],
    ],
  ],
];
function ShortcutsModal() {
  return (
    <>
      <H id="shortcuts" title="Keyboard shortcuts" />
      <div className="modal-b" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(280px,1fr))", gap: 22 }}>
        {SHORTCUTS.map(([g, list]) => (
          <div key={g}>
            <div className="eyebrow" style={{ marginBottom: 6 }}>
              {g}
            </div>
            {list.map(([n, k]) => (
              <div key={n} className="row" style={{ height: 30, fontSize: 13, borderBottom: "1px solid var(--divider)" }}>
                <span className="grow">{n}</span>
                {k.map((x, i) => (
                  <span key={i} style={{ display: "contents" }}>
                    {i > 0 && k[0] === "G" && (
                      <span className="faint" style={{ fontSize: 11 }}>
                        then
                      </span>
                    )}
                    <kbd>{x}</kbd>
                  </span>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}

/* ---------- team ---------- */
type TeamForm = { name: string; desc: string; icon: string; color: string; members: string[] };
function TeamModal({ m }: { m: Modal }) {
  const f = m.form as TeamForm;
  const err = m.err as string | undefined;
  const people = D().members.filter((x) => x.status !== "deactivated");
  const set = (k: keyof TeamForm, v: string) => {
    (f as Record<string, unknown>)[k] = v;
    render();
  };
  const submit = () => {
    f.name = f.name.trim();
    f.desc = f.desc.trim();
    if (!f.name) return ((m.err = "Give the team a name"), render());
    if (teamsList().some((t) => t.name.toLowerCase() === f.name.toLowerCase() && t.id !== m.edit)) return ((m.err = `A team called “${f.name}” already exists`), render());
    let t = m.edit ? team(m.edit as string)! : null;
    mutate(() => {
      if (t) {
        Object.assign(t, { name: f.name, desc: f.desc, icon: f.icon, c: PCOLORS[f.color] });
        D().members.forEach((x) => {
          if (x.team === t!.id && !f.members.includes(x.id)) x.team = "";
        });
      } else {
        t = { id: uid("tm"), name: f.name, desc: f.desc || "No description yet.", icon: f.icon, c: PCOLORS[f.color]! };
        teamsList().push(t);
      }
      f.members.forEach((id) => {
        const x = mem(id);
        if (x) x.team = t!.id;
      });
    });
    closeModal();
    if (m.edit) toast(`Saved ${t!.name}`);
    else {
      go("team", { id: t!.id });
      toast(`Created ${t!.name}`);
    }
  };
  return (
    <>
      <H id="team" title={m.edit ? "Edit team" : "New team"} sub={m.edit ? undefined : "Teams group the people who work on projects together."} />
      <form
        className="modal-b"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
          <span className="picon lg" style={css({ "--c": PCOLORS[f.color]!, marginTop: 22 })} aria-hidden="true">
            <Ic n={f.icon} s={18} />
          </span>
          <div className="field grow">
            <label className="label" htmlFor="tm-name">
              Team name
            </label>
            <input className={`input ${err ? "is-error" : ""}`} id="tm-name" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. Growth" autoFocus aria-invalid={Boolean(err)} />
            {err && (
              <span className="err" role="alert">
                <Ic n="circle-alert" s={12} />
                {err}
              </span>
            )}
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="tm-desc">
            What does this team own?
          </label>
          <input className="input" id="tm-desc" value={f.desc} onChange={(e) => set("desc", e.target.value)} placeholder="e.g. Acquisition experiments and lifecycle email" />
        </div>
        <div className="row" style={{ gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div className="field" style={{ flex: 1, minWidth: 220 }}>
            <span className="label">Icon</span>
            <div className="iconpick" role="radiogroup" aria-label="Icon">
              {PICONS.map((i) => (
                <button key={i} type="button" role="radio" aria-checked={f.icon === i} className={f.icon === i ? "on" : ""} onClick={() => set("icon", i)} aria-label={i}>
                  <Ic n={i} s={15} />
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span className="label">Color</span>
            <div className="swatches" role="radiogroup" aria-label="Color" style={{ maxWidth: 140 }}>
              {Object.entries(PCOLORS).map(([k, v]) => (
                <button key={k} type="button" role="radio" aria-checked={f.color === k} className={`sw ${f.color === k ? "on" : ""}`} style={css({ "--c": v, width: 22, height: 22 })} onClick={() => set("color", k)} aria-label={k}>
                  {f.color === k && <Ic n="check" s={12} />}
                </button>
              ))}
            </div>
          </div>
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ marginBottom: 6 }}>
            Members{" "}
            <span className="faint" style={{ fontWeight: 400 }}>
              · {f.members.length} selected
            </span>
          </legend>
          <div className="panel" style={{ maxHeight: 220, overflowY: "auto", padding: 4 }}>
            {people.map((x) => (
              <label key={x.id} className="mi" style={{ cursor: "pointer", minHeight: 36 }}>
                <input
                  type="checkbox"
                  className="check"
                  checked={f.members.includes(x.id)}
                  onChange={() => {
                    f.members = f.members.includes(x.id) ? f.members.filter((y) => y !== x.id) : [...f.members, x.id];
                    render();
                  }}
                />
                <Av id={x.id} cls="sm" tip={false} />
                <span className="grow trunc">{x.name}</span>
                <span className="r">{x.team && x.team !== m.edit ? TM(x.team).name : ""}</span>
              </label>
            ))}
          </div>
          <span className="hint">Everyone belongs to one primary team. Adding someone here moves them from their current team.</span>
        </fieldset>
      </form>
      <div className="modal-f">
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={submit}>
          {m.edit ? "Save changes" : "Create team"}
        </button>
      </div>
    </>
  );
}

/* ---------- file preview, save view ---------- */
function FilePreviewModal({ m }: { m: Modal }) {
  const f = m.file as FileItem;
  const t = FT[f.type] || FT.other!;
  return (
    <>
      <H id="filePreview" title={f.name} sub={`${t.n} · ${f.size} · Uploaded by ${mem(f.by)?.name || "you"} ${ago(f.at)}`} />
      <div className="modal-b">
        <div style={{ border: "1px solid var(--border)", borderRadius: "var(--r-lg)", overflow: "hidden" }}>
          <FilePrev f={f} />
        </div>
        {Boolean(m.tid) && (
          <div className="row faint" style={{ fontSize: 12.5 }}>
            <Ic n="link" s={13} />
            Attached to{" "}
            <button className="link" onClick={() => (closeModal(), openTask(m.tid as string))}>
              {task(m.tid as string)?.title}
            </button>
          </div>
        )}
      </div>
      <div className="modal-f">
        <button className="btn btn-secondary" onClick={() => void copy(`${location.origin}/w/${currentSlug()}/files/${f.id}`)}>
          <Ic n="link" s={14} />
          Copy link
        </button>
        <span className="sp" />
        <button className="btn btn-primary" onClick={closeModal}>
          Close
        </button>
      </div>
    </>
  );
}
function SaveViewModal({ m }: { m: Modal }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("list");
  const nf = m.nf as number;
  const submit = () => {
    const pid = m.pid as string;
    const sv = { id: uid("v"), project: pid, name: name.trim() || "Untitled view", type, filters: JSON.parse(JSON.stringify(viewOf("p:" + pid).filters)) };
    mutate(() => D().savedViews.push(sv));
    closeModal();
    go("project", { id: proj(pid)!.key, tab: "v:" + sv.id });
    toast(`Saved view “${sv.name}”`);
  };
  return (
    <>
      <H id="saveView" title="Save view" sub="Save the current filters as a tab on this project." />
      <form
        className="modal-b"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="field">
          <label className="label" htmlFor="sv-name">
            View name
          </label>
          <input className="input" id="sv-name" placeholder="e.g. Design review queue" autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label className="label" htmlFor="sv-type">
            Layout
          </label>
          <select className="select" id="sv-type" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="list">List</option>
            <option value="board">Board</option>
            <option value="table">Table</option>
          </select>
        </div>
        {nf ? (
          <div className="hint">
            {nf} filter{nf > 1 ? "s" : ""} will be saved with this view.
          </div>
        ) : (
          <div className="alert info">
            <Ic n="info" s={14} />
            <span>No filters are active — the view will show all tasks. You can add filters after saving.</span>
          </div>
        )}
      </form>
      <div className="modal-f">
        <span className="sp" />
        <button className="btn btn-secondary" onClick={closeModal}>
          Cancel
        </button>
        <button className="btn btn-primary" data-submit onClick={submit}>
          Save view
        </button>
      </div>
    </>
  );
}

export { newTask };
