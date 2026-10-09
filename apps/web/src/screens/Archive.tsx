// Gr8r's archive (gr8r-studio/src/features/archive.js): archived tasks and projects, restore or
// delete for good.
import type { ReactNode } from "react";

import { PSTAT } from "../core/constants";
import { Ic } from "../core/icons";
import { confirmDlg, delProject, deleteTasks, escapeHtml, restore, snapshot } from "../core/more";
import { ago } from "../core/utils";
import { isLive } from "../data/live";
import { D, S, canSee, mutate, proj, render } from "../data/store";
import { Empty, PIcon, StIcon } from "../ui/helpers";
import { toast } from "../ui/toast";

type Archived = { archivedAt?: number };

function restoreTask(id: string) {
  const t = D().tasks.find((x) => x.id === id)!;
  mutate(() => (t.archived = false));
  toast(`Restored “${t.title}”`);
}
function purgeTask(id: string) {
  const t = D().tasks.find((x) => x.id === id)!;
  confirmDlg({
    title: "Delete task permanently?",
    body: `<b>${escapeHtml(t.title)}</b> and its comments will be deleted for everyone. This can't be undone.`,
    ok: "Delete permanently",
    danger: true,
    run: () => {
      const snap = snapshot();
      mutate(() => deleteTasks([t.id]));
      toast(`Deleted “${t.title}”`, isLive() ? {} : { action: "Undo", onAction: () => restore(snap) }); // for good in a real workspace
    },
  });
}
export function restoreProject(id: string) {
  const p = proj(id)!;
  mutate(() => (p.archived = false));
  toast(`Restored ${p.name}`);
}

function Row({ lead, title, sub, when, onRestore, onDelete }: { lead: ReactNode; title: string; sub: ReactNode; when: string; onRestore: () => void; onDelete: () => void }) {
  return (
    <div className="mini" style={{ minHeight: 52, cursor: "default", gap: 12 }}>
      {lead}
      <div className="grow" style={{ minWidth: 0 }}>
        <div className="trunc" style={{ fontWeight: 500 }}>
          {title}
        </div>
        <div className="faint trunc" style={{ fontSize: 12 }}>
          {sub}
        </div>
      </div>
      <span className="faint hide-m" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
        {when}
      </span>
      <button className="btn btn-secondary btn-sm" onClick={onRestore}>
        <Ic n="rotate-ccw" s={13} />
        Restore
      </button>
      <button className="ibtn ibtn-sm" onClick={onDelete} data-tip="Delete permanently" aria-label="Delete permanently" style={{ color: "var(--red)" }}>
        <Ic n="trash-2" s={15} />
      </button>
    </div>
  );
}

export function Archive() {
  const tab = S.ui.archTab;
  const ts = D()
    .tasks.filter((t) => t.archived && canSee(proj(t.project)) && !proj(t.project)?.archived)
    .sort((a, b) => ((b as Archived).archivedAt || 0) - ((a as Archived).archivedAt || 0));
  const ps = D().projects.filter((p) => p.archived);
  const when = (x: Archived) => (x.archivedAt ? "Archived " + ago(x.archivedAt) : "Archived");
  return (
    <div className="page" style={{ maxWidth: 900 }}>
      <div className="ph">
        <div>
          <h1>Archive</h1>
          <p>Archived work is hidden everywhere else. Restore it any time, or delete it for good.</p>
        </div>
      </div>
      <div className="tabs" style={{ marginBottom: 14 }} role="tablist" aria-label="Archive">
        {(
          [
            ["tasks", "Tasks", ts.length],
            ["projects", "Projects", ps.length],
          ] as const
        ).map(([k, n, c]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => ((S.ui.archTab = k), render())}>
            {n}
            <span className="cnt">{c}</span>
          </button>
        ))}
      </div>
      {tab === "tasks" ? (
        ts.length ? (
          <div className="panel" style={{ overflow: "hidden" }}>
            {ts.map((t) => (
              <Row
                key={t.id}
                lead={<StIcon st={t.status} s={15} />}
                title={t.title}
                sub={
                  <>
                    <span className="mono">{t.key}</span> · {proj(t.project)?.name}
                  </>
                }
                when={when(t as Archived)}
                onRestore={() => restoreTask(t.id)}
                onDelete={() => purgeTask(t.id)}
              />
            ))}
          </div>
        ) : (
          <div className="panel">
            <Empty icon="archive" title="No archived tasks" text="Archive finished or abandoned tasks to keep boards focused. They wait here until you restore them." />
          </div>
        )
      ) : ps.length ? (
        <div className="panel" style={{ overflow: "hidden" }}>
          {ps.map((p) => (
            <Row
              key={p.id}
              lead={<PIcon p={p} s={14} />}
              title={p.name}
              sub={`${D().tasks.filter((t) => t.project === p.id).length} tasks · ${PSTAT[p.status].name}`}
              when={when(p as Archived)}
              onRestore={() => restoreProject(p.id)}
              onDelete={() => delProject(p.id)}
            />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty icon="archive" title="No archived projects" text="Archived projects disappear from the sidebar and project lists but keep every task, file, and comment." />
        </div>
      )}
    </div>
  );
}
