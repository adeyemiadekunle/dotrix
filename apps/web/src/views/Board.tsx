// Gr8r's board (gr8r-studio/src/views/board.js): a column per status, cards you drag between and
// within them (core/dragdrop), an inline composer per column, collapsible columns.
import { useState, type CSSProperties } from "react";

import { openPop, openTask, toggleDone } from "../core/actions";
import { PR, STATUSES } from "../core/constants";
import { Ic } from "../core/icons";
import { cancelComposer, commitComposer, editTask, startComposer } from "../core/more";
import { S, commentsOf, pColor, proj, render } from "../data/store";
import type { Task } from "../data/types";
import { Av, Due, Lbl, PrIcon, ProgBar, StIcon, TypeIcon } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;

export function KCard({ t, showProj }: { t: Task; showProj?: boolean }) {
  const cc = commentsOf(t.id).length;
  const ac = t.attachments.length;
  const sd = t.subtasks.filter((s) => s.done).length;
  const p = proj(t.project);
  return (
    <div
      className={`kcard ${t.status === "done" ? "done" : ""}`}
      draggable
      data-drag-card={t.id}
      onClick={() => openTask(t.id)}
      onContextMenu={(e) => {
        e.preventDefault();
        openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id, x: e.clientX, y: e.clientY });
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && openTask(t.id)}
      aria-label={t.title}
    >
      {t.labels.length > 0 && (
        <div className="labels">
          {t.labels.map((l) => (
            <Lbl key={l} id={l} />
          ))}
        </div>
      )}
      <div className="top">
        {t.status === "done" && (
          <span className="done-ic" style={{ margin: "2px 7px 0 0", display: "inline-flex" }} aria-label="Done">
            <StIcon st="done" />
          </span>
        )}
        <div className="title">{t.title}</div>
      </div>
      {t.subtasks.length > 0 && (
        <div className="subp">
          <Ic n="list-checks" s={12} />
          <span className="num">
            {sd}/{t.subtasks.length}
          </span>
          <ProgBar v={Math.round((sd / t.subtasks.length) * 100)} cls={sd === t.subtasks.length ? "green" : ""} />
        </div>
      )}
      <div className="meta">
        {showProj && p && (
          <span className="m" data-tip={p.name}>
            <span className="pdot" style={css({ "--c": pColor(p) })} />
          </span>
        )}
        {t.type !== "task" && (
          <span className="m">
            <TypeIcon type={t.type} s={12} />
          </span>
        )}
        <span className="key">{t.key}</span>
        <button
          className="m"
          onClick={(e) => (e.stopPropagation(), openPop(e.currentTarget, "priority", { id: t.id }))}
          data-tip={PR[t.priority].name}
          aria-label={`Priority: ${PR[t.priority].name}`}
        >
          <PrIcon p={t.priority} s={13} />
        </button>
        {t.due && (
          <button className="m" onClick={(e) => (e.stopPropagation(), openPop(e.currentTarget, "date", { id: t.id, field: "due" }))} aria-label="Due date">
            <Due t={t} />
          </button>
        )}
        {t.recur && (
          <span className="m" data-tip={`Repeats ${t.recur.toLowerCase()}`}>
            <Ic n="repeat" s={12} />
          </span>
        )}
        {cc > 0 && (
          <span className="m" aria-label={`${cc} comments`}>
            <Ic n="message-square" s={12} />
            {cc}
          </span>
        )}
        {ac > 0 && (
          <span className="m" aria-label={`${ac} attachments`}>
            <Ic n="paperclip" s={12} />
            {ac}
          </span>
        )}
        <button
          className="m"
          onClick={(e) => (e.stopPropagation(), openPop(e.currentTarget, "assignee", { id: t.id }))}
          style={{ marginLeft: "auto" }}
          aria-label="Assignee"
        >
          <Av id={t.assignee} cls="sm" />
        </button>
      </div>
      <div className="hacts">
        <button
          className="ibtn ibtn-xs"
          onClick={(e) => (e.stopPropagation(), toggleDone(t.id))}
          data-tip={t.status === "done" ? "Reopen" : "Mark complete"}
          aria-label={t.status === "done" ? "Reopen" : "Mark complete"}
        >
          <Ic n={t.status === "done" ? "rotate-ccw" : "check"} s={13} />
        </button>
        <button className="ibtn ibtn-xs" onClick={(e) => (e.stopPropagation(), editTask(t.id))} data-tip="Quick edit" aria-label="Quick edit">
          <Ic n="pencil" s={12} />
        </button>
        <button className="ibtn ibtn-xs" onClick={(e) => (e.stopPropagation(), openPop(e.currentTarget, "ctx", { ctx: "task", id: t.id }))} aria-label="More">
          <Ic n="ellipsis" s={13} />
        </button>
      </div>
    </div>
  );
}

function CardComposer() {
  const [v, setV] = useState("");
  return (
    <div className="composer">
      <textarea
        autoFocus
        value={v}
        onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            commitComposer(v);
            setV("");
          }
          if (e.key === "Escape") cancelComposer();
        }}
        placeholder="Task name"
        rows={2}
        aria-label="New task name"
      />
      <div className="row">
        <span className="faint" style={{ fontSize: 11 }}>
          Enter to add · Esc to cancel
        </span>
        <span className="sp" />
        <button className="btn btn-sm btn-ghost" onClick={cancelComposer}>
          Cancel
        </button>
        <button className="btn btn-sm btn-primary" onClick={() => (commitComposer(v), setV(""))}>
          Add
        </button>
      </div>
    </div>
  );
}

export function Board({ ts, k, project }: { ts: Task[]; k: string; project?: string }) {
  return (
    <div className="board">
      {STATUSES.map((s) => {
        const col = ts.filter((t) => t.status === s.id).sort((a, b) => a.order - b.order);
        const ck = k + ":" + s.id;
        const gb: Partial<Task> = { status: s.id, ...(project ? { project } : {}) };
        if (S.ui.collapsedCols[ck])
          return (
            <div
              key={s.id}
              className="bcol collapsed"
              onClick={() => {
                delete S.ui.collapsedCols[ck];
                render();
              }}
              data-drop-col={s.id}
              role="button"
              aria-label={`Expand ${s.name}`}
              title="Expand"
            >
              <StIcon st={s.id} />
              <span className="vname">
                {s.name}
                <span className="faint">{col.length}</span>
              </span>
            </div>
          );
        const comp = S.ui.composer && S.ui.composer.key === k && S.ui.composer.group === s.id;
        return (
          <section key={s.id} className="bcol" data-drop-col={s.id} aria-label={s.name}>
            <div className="bcol-h">
              <StIcon st={s.id} />
              <span>{s.name}</span>
              <span className="cnt">{col.length}</span>
              <span className="acts">
                <button className="ibtn ibtn-xs" onClick={() => startComposer(k, s.id, gb)} data-tip="Add task" aria-label={`Add task to ${s.name}`}>
                  <Ic n="plus" s={14} />
                </button>
                <button
                  className="ibtn ibtn-xs"
                  onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "column", id: s.id, key: k })}
                  aria-label="Column options"
                >
                  <Ic n="ellipsis" s={14} />
                </button>
              </span>
            </div>
            <div className="bcol-b" data-col-body={s.id}>
              {col.map((t) => (
                <KCard key={t.id} t={t} showProj={!project} />
              ))}
              {comp ? (
                <CardComposer />
              ) : (
                <button className="addcard" onClick={() => startComposer(k, s.id, gb)}>
                  <Ic n="plus" s={14} />
                  Add task
                </button>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
