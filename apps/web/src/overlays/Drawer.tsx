// Gr8r's task drawer (gr8r-studio/src/overlays/drawer.js + features/subtasks.js): a side panel or
// full page with the task's fields, description, subtasks (each with its own view), attachments,
// comments (@mentions, reactions), and activity. dotrix adds the issue type, and coding: "Start
// coding" asks Claude Code or Codex to work on it, approved like any agent change.
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { applyPatch, closeDrawer, copy, createTask, openPop, toggleDone, toggleFavTask, updateTask } from "../core/actions";
import { agentsNotWired } from "../core/agents";
import { commentDeleted, commentEdited, commentPosted, commentReacted, documentUploaded, isLive, issueFileAttached } from "../data/live";
import { TY, TYPES } from "../core/constants";
import { Ic } from "../core/icons";
import { openModal, restore, snapshot } from "../core/more";
import { currentSlug, go } from "../core/nav";
import { MOD, TODAY, ago, diffD, fmtDate, parse, relDate, uid } from "../core/utils";
import { D, S, commentsOf, isOver, logAct, me, mutate, pColor, proj, render, save, task, who } from "../data/store";
import type { Comment, Subtask, Task } from "../data/types";
import { CellAssignee, CellDue, CellPrio, CellProject, CellStatus } from "../components/TaskList";
import { Av, CommentText, FT, FilePrev, Lbl, ProgBar, fileType, fsize } from "../ui/helpers";
import { toast } from "../ui/toast";

const css = (o: Record<string, string | number>) => o as CSSProperties;

/* ---------- uploads (simulated progress, then the file is attached) ---------- */
interface Upload {
  id: string;
  name: string;
  size: string;
  project: string;
  task?: string;
  pct: number;
}
export let uploads: Upload[] = [];
export function handleFiles(files: FileList | File[] | null, ctx: { project: string; task?: string }) {
  if (!files || !files.length) return;
  if (S.ui.offline) {
    toast("Upload failed — you're offline.", { kind: "err" });
    return;
  }
  [...files].forEach((file) => {
    const up: Upload = { id: uid("u"), name: file.name, size: fsize(file.size), project: ctx.project, task: ctx.task, pct: 0 };
    uploads = [...uploads, up];
    render();
    // A real workspace: the file goes to the API, onto the issue or into the project's files.
    if (isLive()) {
      const onPct = (pct: number) => {
        up.pct = pct;
        render();
      };
      const onIssue = ctx.task ? task(ctx.task) : undefined;
      void (onIssue ? issueFileAttached(file, onIssue, onPct) : documentUploaded(file, ctx.project, onPct))
        .then(() => toast(`Uploaded ${up.name}`))
        .catch((e) => toast(`${up.name} didn't upload${e instanceof Error ? `: ${e.message}` : ""}`, { kind: "err", ms: 6000 }))
        .finally(() => {
          uploads = uploads.filter((x) => x !== up);
          render();
        });
      return;
    }
    const iv = setInterval(() => {
      up.pct = Math.min(100, up.pct + 9 + Math.round(Math.random() * 22));
      render();
      if (up.pct >= 100) {
        clearInterval(iv);
        uploads = uploads.filter((x) => x !== up);
        const rec = { id: uid("f"), name: up.name, type: fileType(up.name), size: up.size, by: D().me, at: Date.now() };
        mutate(() => {
          D().files.unshift({ ...rec, project: up.project, task: up.task });
          if (up.task) {
            const t = task(up.task)!;
            t.attachments.push(rec);
            logAct("added a file to", t, up.name);
          }
        });
        toast(`Uploaded ${up.name}`);
      }
    }, 160);
  });
}

/* ---------- comments ---------- */
export function postComment(id: string) {
  const txt = (S.ui.drafts[id] || "").trim();
  if (!txt) return;
  const t = task(id)!;
  mutate(() => {
    D().comments.push({ id: uid("c"), task: id, by: D().me, at: Date.now(), text: txt, re: {} });
    logAct("commented on", t);
    S.ui.drafts[id] = "";
    S.ui.mention = null;
    S.ui.drawerTab = "comments";
  });
  // Who was @mentioned by name, so the API tells them.
  commentPosted(t, txt, D().members.filter((m) => txt.includes(`@${m.name}`)).map((m) => m.id));
}
/** Add or take back your reaction to a comment. */
export function toggleReaction(c: Comment, e: string) {
  const on = !(c.re[e] || []).includes(D().me);
  mutate(() => {
    const list = c.re[e] || [];
    c.re[e] = on ? [...list, D().me] : list.filter((x) => x !== D().me);
  });
  commentReacted(c, e, on);
}
export function CommentItem({ c }: { c: Comment }) {
  const w = who(c.by);
  const mine = c.by === D().me;
  // Your own comments, and anyone's for owners and admins.
  const canDelete = mine || ["Owner", "Admin"].includes(me()?.role ?? "");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(c.text);
  const saveEdit = () => {
    const v = draft.trim();
    setEditing(false);
    if (!v || v === c.text) return;
    mutate(() => (c.text = v));
    commentEdited(c);
  };
  return (
    <div className="cmt">
      <Av id={c.by} cls="md" tip={false} />
      <div className="body">
        <div className="who">
          <b>{w?.name}</b>
          <time>{ago(c.at)}</time>
          {canDelete && (
            <>
              <span className="sp" />
              {mine && !editing && (
                <button
                  className="ibtn ibtn-xs"
                  aria-label="Edit comment"
                  data-tip="Edit"
                  onClick={() => {
                    setDraft(c.text);
                    setEditing(true);
                  }}
                >
                  <Ic n="pencil" s={12} />
                </button>
              )}
              <button
                className="ibtn ibtn-xs"
                aria-label="Delete comment"
                data-tip="Delete"
                onClick={() => {
                  const snap = snapshot();
                  mutate(() => (D().comments = D().comments.filter((x) => x !== c)));
                  if (isLive()) {
                    commentDeleted(c); // for good: no undo
                    toast("Comment deleted");
                  } else toast("Comment deleted", { action: "Undo", onAction: () => restore(snap) });
                }}
              >
                <Ic n="trash-2" s={12} />
              </button>
            </>
          )}
        </div>
        {editing ? (
          <div className="txt">
            <textarea
              className="input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) saveEdit();
                if (e.key === "Escape") {
                  e.stopPropagation();
                  setEditing(false);
                }
              }}
              aria-label="Edit comment"
              rows={3}
              autoFocus
              style={{ width: "100%", resize: "vertical" }}
            />
            <div className="row" style={{ gap: 6, marginTop: 6 }}>
              <button className="btn btn-primary btn-sm" onClick={saveEdit}>
                Save
              </button>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="txt">
            <CommentText text={c.text} />
          </div>
        )}
        <div className="reacts">
          {Object.entries(c.re || {})
            .filter(([, v]) => v.length)
            .map(([e, v]) => (
              <button
                key={e}
                className={`react ${v.includes(D().me) ? "mine" : ""}`}
                aria-label={`${e} ${v.length}`}
                title={v.map((i) => who(i)?.name).join(", ")}
                onClick={() => toggleReaction(c, e)}
              >
                {e}
                <span className="num">{v.length}</span>
              </button>
            ))}
          <button className="react" aria-label="Add reaction" style={{ color: "var(--text-3)" }} onClick={(e) => openPop(e.currentTarget, "emoji", { id: c.id })}>
            <Ic n="smile-plus" s={13} />
          </button>
        </div>
      </div>
    </div>
  );
}
/** The comment box with @mentions (the drawer and the Inbox's reply). */
export function CommentBox({ t, id = "d-cmt", placeholder = "Leave a comment… type @ to mention", label = "Comment" }: { t: Task; id?: string; placeholder?: string; label?: string }) {
  const draft = S.ui.drafts[t.id] || "";
  const ref = useRef<HTMLTextAreaElement>(null);
  const ment =
    S.ui.mention && S.ui.mention.tid === t.id
      ? D()
          .members.filter((m) => {
            const q = S.ui.mention!.q.toLowerCase();
            return m.name.toLowerCase().startsWith(q) || m.name.split(" ")[1]?.toLowerCase().startsWith(q);
          })
          .slice(0, 5)
      : [];
  const onChange = (el: HTMLTextAreaElement) => {
    S.ui.drafts[t.id] = el.value;
    const before = el.value.slice(0, el.selectionStart);
    const m = before.match(/(?:^|\s)@([A-Za-z]*)$/);
    S.ui.mention = m ? { tid: t.id, q: m[1]! } : null;
    el.style.height = "auto";
    el.style.height = el.scrollHeight + "px";
    render();
  };
  const pickMention = (name: string) => {
    S.ui.drafts[t.id] = draft.replace(/@([A-Za-z]*)$/, "@" + name + " ");
    S.ui.mention = null;
    render();
    ref.current?.focus();
  };
  return (
    <div className="grow" style={{ position: "relative" }}>
      <div className="cbox">
        <textarea
          ref={ref}
          id={id}
          value={draft}
          onChange={(e) => onChange(e.target)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) postComment(t.id);
          }}
          placeholder={placeholder}
          aria-label={label}
          rows={2}
        />
        <div className="row">
          <button
            className="ibtn ibtn-xs"
            data-tip="Mention someone"
            aria-label="Mention"
            onClick={() => {
              S.ui.drafts[t.id] = draft + (draft && !draft.endsWith(" ") ? " @" : "@");
              S.ui.mention = { tid: t.id, q: "" };
              render();
              ref.current?.focus();
            }}
          >
            <Ic n="at-sign" s={14} />
          </button>
          <label className="ibtn ibtn-xs" data-tip="Attach file" style={{ cursor: "pointer" }}>
            <Ic n="paperclip" s={14} />
            <input type="file" multiple hidden onChange={(e) => handleFiles(e.target.files, { project: t.project, task: t.id })} />
          </label>
          <span className="sp" />
          <span className="faint hide-m" style={{ fontSize: 11 }}>
            {MOD}+Enter
          </span>
          <button className="btn btn-primary btn-sm" onClick={() => postComment(t.id)}>
            Comment
          </button>
        </div>
      </div>
      {ment.length > 0 && (
        <div className="pop" style={{ position: "absolute", top: "auto", bottom: "calc(100% + 4px)", left: 0 }}>
          {ment.map((m) => (
            <button key={m.id} className="mi" onClick={() => pickMention(m.name)}>
              <Av id={m.id} cls="sm" tip={false} />
              {m.name}
              <span className="r">{m.title}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- the rich-text description ---------- */
function Rte({ t }: { t: Task }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current && document.activeElement !== ref.current && ref.current.innerHTML !== t.desc) ref.current.innerHTML = t.desc;
  }, [t.desc]);
  const cmd = (c: string) => {
    ref.current?.focus();
    if (c === "createLink") {
      const url = prompt("Link address");
      if (url) document.execCommand("createLink", false, url);
    } else if (c.startsWith("formatBlock:")) document.execCommand("formatBlock", false, c.split(":")[1]);
    else document.execCommand(c);
  };
  return (
    <div className="dsec">
      <div className="dsec-h">
        <h3 id="d-desc-l">Description</h3>
        <div className="rte-tb" role="toolbar" aria-label="Formatting" aria-controls="d-desc">
          {(
            [
              ["bold", "bold", "Bold"],
              ["italic", "italic", "Italic"],
              ["insertUnorderedList", "list", "Bulleted list"],
              ["insertOrderedList", "list-ordered", "Numbered list"],
              ["formatBlock:h4", "heading", "Heading"],
              ["createLink", "link", "Link"],
            ] as const
          ).map(([c, i, n]) => (
            <button key={c} className="ibtn ibtn-xs" data-tip={n} aria-label={n} onMouseDown={(e) => (e.preventDefault(), cmd(c))}>
              <Ic n={i} s={13} />
            </button>
          ))}
        </div>
      </div>
      <div className="rte">
        <div
          ref={ref}
          className="rte-body"
          id="d-desc"
          contentEditable
          suppressContentEditableWarning
          data-ph="Add a description…"
          role="textbox"
          aria-multiline="true"
          aria-labelledby="d-desc-l"
          onBlur={(e) => {
            const html = e.currentTarget.innerHTML;
            if (html !== t.desc) mutate(() => applyPatch(t, { desc: html }));
          }}
        />
      </div>
    </div>
  );
}

/* ---------- subtasks ---------- */
function toggleSub(t: Task, s: Subtask) {
  mutate(() => {
    s.done = !s.done;
    logAct(s.done ? "completed subtask on" : "reopened subtask on", t, `“${s.title}”`);
  });
}
function SubtaskView({ t, s }: { t: Task; s: Subtask & { note?: string } }) {
  const i = t.subtasks.indexOf(s);
  const [title, setTitle] = useState(s.title);
  const nav = (d: number) => {
    const n = t.subtasks[i + d];
    if (n) {
      S.ui.subOpen = { tid: t.id, sid: n.id };
      render();
    }
  };
  const promote = () => {
    let n: Task | undefined;
    mutate(() => {
      n = createTask({
        title: s.title,
        project: t.project,
        status: s.done ? "done" : "todo",
        assignee: s.assignee || t.assignee,
        priority: t.priority,
        due: s.due || null,
        labels: [...t.labels],
        desc: s.note ? `<p>${s.note}</p>` : "",
      });
      t.subtasks = t.subtasks.filter((x) => x !== s);
      logAct("converted a subtask of", t, `into ${n.key}`);
    });
    S.ui.subOpen = null;
    render();
    toast(`Converted to ${n!.key}`, { action: "Open", onAction: () => openTaskById(n!.id) });
  };
  return (
    <div className="subview">
      <button className="pillbtn" onClick={() => ((S.ui.subOpen = null), render())} style={{ margin: "-4px 0 14px -7px", fontSize: 12.5, color: "var(--text-2)" }}>
        <Ic n="arrow-left" s={14} />
        <span className="trunc" style={{ maxWidth: 420 }}>
          {t.title}
        </span>
      </button>
      <div className="row" style={{ gap: 10, alignItems: "flex-start" }}>
        <input type="checkbox" className="check round" style={{ marginTop: 9 }} checked={s.done} onChange={() => toggleSub(t, s)} aria-label={s.done ? "Mark subtask not done" : "Mark subtask done"} />
        <textarea
          className="ttl-edit"
          rows={1}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => title.trim() && title.trim() !== s.title && mutate(() => ((s.title = title.trim()), (t.updated = Date.now())))}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), e.currentTarget.blur())}
          aria-label="Subtask title"
          style={s.done ? { textDecoration: "line-through", color: "var(--text-3)" } : undefined}
        />
      </div>
      <div className="faint" style={{ fontSize: 12, margin: "4px 0 0 26px" }}>
        Subtask {i + 1} of {t.subtasks.length} · {s.done ? "Done" : "Open"}
      </div>
      <dl className="kv" style={{ marginTop: 16 }}>
        <dt>
          <Ic n="user" s={14} />
          Assignee
        </dt>
        <dd>
          <button className={`pillbtn ${s.assignee ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "subassignee", { id: t.id, i })}>
            <Av id={s.assignee} cls="sm" tip={false} />
            <span>{s.assignee ? who(s.assignee)?.name : "Unassigned"}</span>
          </button>
        </dd>
        <dt>
          <Ic n="calendar" s={14} />
          Due date
        </dt>
        <dd>
          <button className={`pillbtn ${s.due ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "date", { id: t.id, i, field: "subdue" })}>
            <Ic n="calendar" s={13} />
            <span className="num">{s.due ? relDate(s.due) : "Set date"}</span>
          </button>
        </dd>
        <dt>
          <Ic n="folder" s={14} />
          Parent
        </dt>
        <dd>
          <button className="pillbtn" onClick={() => ((S.ui.subOpen = null), render())}>
            <span className="mono faint" style={{ fontSize: 11 }}>
              {t.key}
            </span>
            {t.title}
          </button>
        </dd>
      </dl>
      <div className="dsec">
        <div className="dsec-h">
          <h3 id="s-note-l">Notes</h3>
        </div>
        <textarea
          className="textarea"
          rows={4}
          defaultValue={s.note || ""}
          onChange={(e) => {
            s.note = e.target.value;
            save();
          }}
          placeholder="Add details, links, or acceptance criteria…"
          aria-labelledby="s-note-l"
        />
      </div>
      <div className="dsec row" style={{ gap: 6, flexWrap: "wrap" }}>
        <button className="btn btn-secondary btn-sm" onClick={promote}>
          <Ic n="arrow-up-right" s={13} />
          Convert to task
        </button>
        <span className="sp" />
        <button className="btn btn-sm btn-ghost" onClick={() => nav(-1)} disabled={i === 0} aria-label="Previous subtask">
          <Ic n="chevron-left" s={14} />
          Previous
        </button>
        <button className="btn btn-sm btn-ghost" onClick={() => nav(1)} disabled={i === t.subtasks.length - 1} aria-label="Next subtask">
          Next
          <Ic n="chevron-right" s={14} />
        </button>
        <button
          className="btn btn-sm btn-danger-ghost"
          onClick={() => {
            S.ui.subOpen = null;
            mutate(() => {
              t.subtasks = t.subtasks.filter((x) => x !== s);
              logAct("removed a subtask from", t, `“${s.title}”`);
            });
          }}
        >
          <Ic n="trash-2" s={13} />
          Delete
        </button>
      </div>
    </div>
  );
}
function openTaskById(id: string) {
  S.ui.drawer = id;
  S.ui.subOpen = null;
  render();
}

/* ---------- dotrix: coding ---------- */
function CodingSection({ t }: { t: Task }) {
  const sessions = D().coding.filter((c) => c.task === t.id);
  const latest = sessions[0];
  const start = (tool: "claude-code" | "codex") => {
    S.ui.pop = null;
    if (agentsNotWired()) return;
    mutate(() => {
      D().coding.unshift({ id: uid("cs"), project: t.project, task: t.id, tool, status: "awaiting_approval", by: D().me, at: Date.now(), turns: [{ at: Date.now(), ask: t.title, events: [] }] });
      D().notifs.unshift({ id: uid("n"), type: "approval", by: `agent:${tool}`, project: t.project, task: t.id, text: "is waiting to start coding", snippet: `${t.key} ${t.title}`, at: Date.now(), read: false });
    });
    toast(`${tool === "codex" ? "Codex" : "Claude Code"} will start once someone approves`, { action: "Open Chat", onAction: () => go("chat", {}, { search: "tab=coding" }) });
  };
  const label: Record<string, [string, string]> = {
    awaiting_approval: ["Waiting for approval", "amber"],
    queued: ["Queued", ""],
    running: ["Coding", "accent"],
    pr_opened: ["PR opened", "green"],
    no_changes: ["No changes", ""],
    failed: ["Failed", "red"],
    stopped: ["Stopped", ""],
    rejected: ["Rejected", "red"],
  };
  return (
    <div className="dsec">
      <div className="dsec-h">
        <h3>Coding</h3>
        <span className="cnt">{sessions.length}</span>
        <div className="acts">
          <button className="btn btn-sm btn-ghost" onClick={() => start("claude-code")}>
            <Ic n="bot" s={13} />
            Start coding
          </button>
        </div>
      </div>
      {latest ? (
        <div className="panel" style={{ padding: "10px 12px" }}>
          <div className="row" style={{ gap: 8 }}>
            <Av id={`agent:${latest.tool}`} cls="sm" tip={false} />
            <b style={{ fontWeight: 500, fontSize: 13 }}>{latest.tool === "codex" ? "Codex" : "Claude Code"}</b>
            <span className={`badge ${label[latest.status]![1]}`}>{label[latest.status]![0]}</span>
            <span className="sp" />
            <span className="faint" style={{ fontSize: 11.5 }}>
              {ago(latest.at)}
            </span>
          </div>
          {latest.turns.at(-1)?.summary && (
            <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>
              {latest.turns.at(-1)!.summary}
            </p>
          )}
          <div className="row" style={{ gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {latest.pr && (
              <a className="btn btn-sm btn-secondary" href={latest.pr.url} target="_blank" rel="noreferrer">
                <Ic n="git-pull-request" s={13} />
                PR #{latest.pr.number} · {latest.pr.state}
              </a>
            )}
            <button className="btn btn-sm btn-ghost" onClick={() => go("chat", {}, { search: `tab=coding&session=${latest.id}` })}>
              <Ic n="arrow-up-right" s={13} />
              Open the session
            </button>
          </div>
        </div>
      ) : (
        <p className="faint" style={{ fontSize: 12.5, margin: "4px 0" }}>
          Claude Code or Codex can work on this in a sandbox and open a pull request. Someone who may approve agent changes starts it.
        </p>
      )}
    </div>
  );
}

/* ---------- the drawer ---------- */
export function Drawer() {
  const id = S.ui.drawer;
  const t = id ? task(id) : undefined;
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (t && ref.current && !ref.current.contains(document.activeElement)) ref.current.focus({ preventScroll: true });
  }, [id]);
  useEffect(() => {
    if (!t) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !S.ui.pop && !S.ui.modals.length) closeDrawer();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [id]);
  if (!t) return null;
  const p = proj(t.project)!;
  const u = S.ui;
  const cs = commentsOf(t.id);
  const sd = t.subtasks.filter((s) => s.done).length;
  const acts = D().activity.filter((a) => a.task === t.id);
  const tab = u.drawerTab;
  const ups = uploads.filter((x) => x.task === t.id);
  const sub = u.subOpen && u.subOpen.tid === t.id ? t.subtasks.find((s) => s.id === u.subOpen!.sid) : undefined;
  const prop = (icon: string, label: string, val: ReactNode) => (
    <>
      <dt>
        <Ic n={icon} s={14} />
        {label}
      </dt>
      <dd>{val}</dd>
    </>
  );
  return (
    <>
      {u.drawerFull && <div className="drawer-scrim full enter" onClick={closeDrawer} />}
      <aside ref={ref} className={`drawer enter ${u.drawerFull ? "full" : ""}`} role="dialog" aria-modal={u.drawerFull} aria-labelledby="d-h" tabIndex={-1}>
        <h2 className="sr" id="d-h">
          {sub ? "Subtask: " + sub.title : "Task: " + t.title}
        </h2>
        <div className="drawer-h">
          <button className="pillbtn" onClick={() => go("project", { id: p.key, tab: "board" })} style={{ fontSize: 12.5 }}>
            <span className="pdot" style={css({ "--c": pColor(p) })} />
            {p.name}
          </button>
          <span className="faint">/</span>
          <span className="mono faint" style={{ fontSize: 11.5, padding: "0 6px" }}>
            {t.key}
          </span>
          <span className="sp" />
          <button className={`btn btn-sm ${t.status === "done" ? "btn-secondary" : "btn-ghost"}`} onClick={() => toggleDone(t.id)} style={t.status === "done" ? { color: "var(--green)" } : undefined}>
            <Ic n={t.status === "done" ? "circle-check" : "circle"} s={14} />
            <span className="hide-m">{t.status === "done" ? "Completed" : "Mark complete"}</span>
          </button>
          <button className="ibtn ibtn-sm" onClick={() => toggleFavTask(t.id)} data-tip={t.fav ? "Unfavorite" : "Favorite"} aria-pressed={t.fav} aria-label="Favorite" style={t.fav ? { color: "var(--amber)" } : undefined}>
            <Ic n="star" s={15} />
          </button>
          <button className="ibtn ibtn-sm" onClick={() => void copy(`${location.origin}/w/${currentSlug()}/p/${p.key}/board?task=${t.key}`)} data-tip="Copy link" aria-label="Copy link">
            <Ic n="link" s={15} />
          </button>
          <button className="ibtn ibtn-sm hide-m" onClick={() => ((u.drawerFull = !u.drawerFull), render())} data-tip={u.drawerFull ? "Side panel" : "Full page"} aria-label="Toggle full page">
            <Ic n={u.drawerFull ? "minimize-2" : "maximize-2"} s={15} />
          </button>
          <button className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id })} aria-label="More">
            <Ic n="ellipsis" s={15} />
          </button>
          <button className="ibtn ibtn-sm" onClick={closeDrawer} data-tip="Close  Esc" aria-label="Close">
            <Ic n="x" s={16} />
          </button>
        </div>
        <div className="drawer-b">
          {sub ? (
            <SubtaskView key={sub.id} t={t} s={sub} />
          ) : (
            <>
              {t.status === "done" ? (
                <div className="alert ok" style={{ marginBottom: 12 }}>
                  <Ic n="circle-check" s={15} />
                  <span>
                    Completed {t.completedAt ? ago(t.completedAt) : ""}.{" "}
                    <button className="link" onClick={() => toggleDone(t.id)}>
                      Reopen task
                    </button>
                  </span>
                </div>
              ) : isOver(t) ? (
                <div className="alert danger" style={{ marginBottom: 12 }}>
                  <Ic n="clock-alert" s={15} />
                  <span>
                    Overdue by {-diffD(parse(t.due)!, TODAY)} day{-diffD(parse(t.due)!, TODAY) > 1 ? "s" : ""}.{" "}
                    <button className="link" onClick={(e) => openPop(e.currentTarget, "date", { id: t.id, field: "due" })}>
                      Reschedule
                    </button>
                  </span>
                </div>
              ) : null}
              <DrawerTitle t={t} />
              <dl className="kv" style={{ marginTop: 12, ...(u.drawerFull ? { gridTemplateColumns: "112px minmax(0,1fr) 112px minmax(0,1fr)" } : {}) }}>
                {prop("circle-dot", "Status", <CellStatus t={t} />)}
                {prop("signal-high", "Priority", <CellPrio t={t} />)}
                {prop("user", "Assignee", <CellAssignee t={t} />)}
                {prop("calendar", "Due date", <CellDue t={t} />)}
                {prop(
                  "calendar-arrow-up",
                  "Start date",
                  <button className={`pillbtn ${t.start ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "date", { id: t.id, field: "start" })}>
                    <Ic n="calendar" s={13} />
                    {t.start ? fmtDate(t.start) : "Set date"}
                  </button>,
                )}
                {prop("folder", "Project", <CellProject t={t} />)}
                {prop(
                  TY[t.type].icon,
                  "Type",
                  <select
                    className="select"
                    style={{ width: "auto", height: 26, fontSize: 12.5, borderColor: "transparent", backgroundColor: "transparent" }}
                    value={t.type}
                    aria-label="Type"
                    onChange={(e) => updateTask(t.id, { type: e.target.value as Task["type"] })}
                  >
                    {TYPES.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.name}
                      </option>
                    ))}
                  </select>,
                )}
                {prop(
                  "tag",
                  "Labels",
                  <button className={`pillbtn ${t.labels.length ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "labels", { id: t.id })} style={{ flexWrap: "wrap", height: "auto", minHeight: 26, padding: "3px 7px" }}>
                    {t.labels.length ? (
                      t.labels.map((l) => <Lbl key={l} id={l} />)
                    ) : (
                      <>
                        <Ic n="tag" s={13} />
                        Add labels
                      </>
                    )}
                  </button>,
                )}
                {prop(
                  "repeat",
                  "Repeat",
                  <button className={`pillbtn ${t.recur ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "recur", { id: t.id })}>
                    <Ic n="repeat" s={13} />
                    {t.recur || "Does not repeat"}
                  </button>,
                )}
                {prop(
                  "timer",
                  "Estimate",
                  <button className={`pillbtn ${t.estimate ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "estimate", { id: t.id })}>
                    <Ic n="timer" s={13} />
                    {t.estimate || "Add estimate"}
                  </button>,
                )}
                {prop(
                  "git-branch",
                  "Blocked by",
                  <button className={`pillbtn ${t.deps.length ? "" : "empty"}`} onClick={(e) => openPop(e.currentTarget, "deps", { id: t.id })} style={{ height: "auto", minHeight: 26, flexWrap: "wrap" }}>
                    {t.deps.length ? (
                      t.deps.map((d) =>
                        task(d) ? (
                          <span key={d} style={{ display: "contents" }}>
                            <span className="depchip mono" style={{ fontSize: 11, padding: "1px 5px", borderRadius: 4, background: "var(--surface-3)" }}>
                              {task(d)!.key}
                            </span>
                            <span className="trunc" style={{ maxWidth: 160 }}>
                              {task(d)!.title}
                            </span>
                          </span>
                        ) : null,
                      )
                    ) : (
                      <>
                        <Ic n="git-branch" s={13} />
                        None
                      </>
                    )}
                  </button>,
                )}
              </dl>
              <Rte t={t} />
              <Subtasks t={t} sd={sd} />
              <div className="dsec">
                <div className="dsec-h">
                  <h3>Attachments</h3>
                  <span className="cnt">{t.attachments.length}</span>
                  <div className="acts">
                    <label className="btn btn-sm btn-ghost" style={{ cursor: "pointer" }}>
                      <Ic n="upload" s={13} />
                      Upload
                      <input type="file" multiple hidden onChange={(e) => handleFiles(e.target.files, { project: t.project, task: t.id })} />
                    </label>
                  </div>
                </div>
                {ups.map((x) => (
                  <div key={x.id} className="upl" style={{ marginBottom: 6 }}>
                    <span className="ftype" style={css({ "--c": FT[fileType(x.name)]!.c })}>
                      <Ic n={FT[fileType(x.name)]!.i} s={14} />
                    </span>
                    <div className="grow">
                      <div className="row">
                        <span className="trunc">{x.name}</span>
                        <span className="sp" />
                        <span className="faint num" style={{ fontSize: 11 }}>
                          {x.pct}%
                        </span>
                      </div>
                      <div className="prog" style={{ marginTop: 5 }}>
                        <i style={css({ "--p": x.pct / 100 })} />
                      </div>
                    </div>
                  </div>
                ))}
                {t.attachments.length > 0 ? (
                  <div className="att">
                    {t.attachments.map((f) => (
                      <div key={f.id} className="attc" onClick={() => openModal({ type: "filePreview", file: f, tid: t.id })} role="button" tabIndex={0}>
                        <FilePrev f={f} />
                        <div className="fi">
                          <div className="trunc" style={{ fontWeight: 500 }}>
                            {f.name}
                          </div>
                          <div className="faint">
                            {FT[f.type]?.n || "File"} · {f.size}
                          </div>
                        </div>
                        <button
                          className="ibtn ibtn-xs x"
                          aria-label="Remove attachment"
                          onClick={(e) => {
                            e.stopPropagation();
                            mutate(() => {
                              t.attachments = t.attachments.filter((a) => a.id !== f.id);
                              logAct("removed a file from", t);
                            });
                            toast(`Removed ${f.name}`);
                          }}
                        >
                          <Ic n="x" s={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  !ups.length && (
                    <label
                      className="dropzone"
                      style={{ padding: 12 }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        handleFiles(e.dataTransfer.files, { project: t.project, task: t.id });
                      }}
                    >
                      <Ic n="paperclip" s={15} />
                      <span>Drop files or click to attach</span>
                      <input type="file" multiple hidden onChange={(e) => handleFiles(e.target.files, { project: t.project, task: t.id })} />
                    </label>
                  )
                )}
              </div>
              <CodingSection t={t} />
              <div className="dsec">
                <div className="tabs" style={{ marginBottom: 6 }}>
                  {(
                    [
                      ["comments", "Comments", cs.length],
                      ["activity", "Activity", acts.length],
                    ] as const
                  ).map(([k, n, c]) => (
                    <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => ((u.drawerTab = k), render())}>
                      {n}
                      <span className="cnt">{c}</span>
                    </button>
                  ))}
                </div>
                {tab === "comments" ? (
                  <>
                    {cs.length ? (
                      cs.map((c) => <CommentItem key={c.id} c={c} />)
                    ) : (
                      <p className="faint" style={{ fontSize: 13, margin: "10px 0" }}>
                        No comments yet. Start the conversation.
                      </p>
                    )}
                    <div className="row" style={{ alignItems: "flex-start", gap: 10, marginTop: 8 }}>
                      <Av id={D().me} cls="md" tip={false} />
                      <CommentBox t={t} />
                    </div>
                  </>
                ) : (
                  <div style={{ paddingTop: 4 }}>
                    {acts.map((a) => (
                      <div key={a.id} className="act-line">
                        <span className="ico">
                          <Av id={a.by} cls="sm" tip={false} />
                        </span>
                        <span className="grow">
                          <b>{a.by === D().me ? "You" : who(a.by)?.name}</b> {a.verb.replace(/ of$/, "")}
                          {a.extra ? " " + a.extra : ""}
                        </span>
                        <time className="faint" style={{ fontSize: 11.5 }}>
                          {ago(a.at)}
                        </time>
                      </div>
                    ))}
                    <div className="act-line">
                      <span className="ico">
                        <Ic n="plus" s={13} />
                      </span>
                      <span className="grow">Task created</span>
                      <time className="faint" style={{ fontSize: 11.5 }}>
                        {ago(t.created)}
                      </time>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function DrawerTitle({ t }: { t: Task }) {
  const [v, setV] = useState(t.title);
  useEffect(() => setV(t.title), [t.id, t.title]);
  return (
    <textarea
      className="ttl-edit"
      id="d-title"
      rows={1}
      value={v}
      onChange={(e) => {
        setV(e.target.value);
        e.target.style.height = "auto";
        e.target.style.height = e.target.scrollHeight + "px";
      }}
      onBlur={() => v.trim() && v.trim() !== t.title && updateTask(t.id, { title: v.trim() })}
      onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), e.currentTarget.blur())}
      aria-label="Task title"
    />
  );
}

function Subtasks({ t, sd }: { t: Task; sd: number }) {
  const [v, setV] = useState("");
  return (
    <div className="dsec">
      <div className="dsec-h">
        <h3>Subtasks</h3>
        <span className="cnt num">
          {sd}/{t.subtasks.length}
        </span>
        {t.subtasks.length > 0 && (
          <span style={{ width: 90, display: "flex" }}>
            <ProgBar v={Math.round((sd / t.subtasks.length) * 100)} cls={sd === t.subtasks.length ? "green" : ""} />
          </span>
        )}
      </div>
      {t.subtasks.map((s) => (
        <div key={s.id} className={`subt ${s.done ? "done" : ""}`}>
          <input type="checkbox" className="check" checked={s.done} onChange={() => toggleSub(t, s)} aria-label={`${s.done ? "Reopen" : "Complete"} subtask ${s.title}`} />
          <button className="s" onClick={() => ((S.ui.subOpen = { tid: t.id, sid: s.id }), render())}>
            {s.title}
          </button>
          {s.due && (
            <span className={`due ${!s.done && diffD(parse(s.due)!, TODAY) < 0 ? "over" : ""}`}>
              <Ic n="calendar" s={12} />
              {relDate(s.due)}
            </span>
          )}
          {s.assignee && <Av id={s.assignee} cls="sm" />}
          <button className="ibtn ibtn-xs x" onClick={() => ((S.ui.subOpen = { tid: t.id, sid: s.id }), render())} aria-label="Open subtask details" tabIndex={-1}>
            <Ic n="chevron-right" s={14} />
          </button>
        </div>
      ))}
      <div className="subt" style={{ color: "var(--text-3)" }}>
        <Ic n="plus" s={15} />
        <input
          className="inline-in"
          id="d-sub"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && v.trim()) {
              const title = v.trim();
              mutate(() => {
                t.subtasks.push({ id: uid("s"), title, done: false });
                logAct("added subtask to", t, `“${title}”`);
              });
              setV("");
            }
          }}
          placeholder="Add subtask"
          aria-label="Add subtask"
          style={{ fontSize: 13.5 }}
        />
      </div>
    </div>
  );
}
