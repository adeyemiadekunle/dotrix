// Task pages: the same views over every project you can see.
import { Ic } from "../core/icons";
import { confirmDlg, deleteTasks, escapeHtml, newTask, restore, snapshot } from "../core/more";
import { go } from "../core/nav";
import { TODAY, ago, dOff, diffD, parse } from "../core/utils";
import { isLive, live } from "../data/live";
import { useLiveArchivedTasks, useLiveMyTasks, useLiveStarredTasks } from "../../lib/workspace-data";
import { D, S, allTasks, canSee, isOver, mutate, proj, render } from "../data/store";
import { ListView, MiniRow } from "../components/TaskList";
import { applyView, viewOf, ViewToolbar, type Group } from "../shell/viewEngine";
import { Empty, StIcon } from "../ui/helpers";
import { toast } from "../ui/toast";

export function MyTasks() {
  const k = "mytasks";
  const view = S.ui.myTab;
  const setView = (v: typeof view) => ((S.ui.myTab = v), render());
  const v = viewOf(k);
  const ws = live.ws?.id;
  const liveMine = useLiveMyTasks(ws, isLive());
  const mine = applyView(
    (isLive() ? (liveMine ?? []) : allTasks()).filter((t) => t.assignee === D().me),
    v.sort.f === "manual" ? { ...v, sort: { f: "due", dir: 1 } } : v,
  );
  const groups: Group[] = [
    {
      key: "overdue",
      name: "Overdue",
      html: (
        <span style={{ color: "var(--red)" }}>
          <Ic n="clock-alert" s={14} />
        </span>
      ),
      tasks: mine.filter(isOver),
      set: {},
    },
    {
      key: "today",
      name: "Today",
      html: <Ic n="sun" s={14} />,
      tasks: mine.filter((t) => t.status !== "done" && t.due && diffD(parse(t.due)!, TODAY) === 0),
      set: { due: dOff(0) },
    },
    {
      key: "upcoming",
      name: "Upcoming",
      html: <Ic n="calendar-days" s={14} />,
      tasks: mine.filter((t) => t.status !== "done" && (!t.due || diffD(parse(t.due)!, TODAY) > 0)),
      set: { due: dOff(3) },
    },
    {
      key: "completed",
      name: "Completed",
      html: (
        <span style={{ color: "var(--green)" }}>
          <Ic n="circle-check" s={14} />
        </span>
      ),
      tasks: mine.filter((t) => t.status === "done"),
      set: { status: "done" },
    },
  ];
  // Completed starts folded.
  if (S.ui.collapsedGroups[k + ":completed"] === undefined) S.ui.collapsedGroups[k + ":completed"] = true;
  return (
    <div className="page flush">
      <div className="ph">
        <div>
          <h1>My Tasks</h1>
          <p>
            {groups[1]!.tasks.length} due today · {groups[0]!.tasks.length} overdue · {groups[2]!.tasks.length} upcoming
          </p>
        </div>
        <div className="acts">
          <button className="btn btn-primary" onClick={() => newTask({ assignee: D().me })}>
            <Ic n="plus" s={14} />
            New task
          </button>
        </div>
      </div>
      <div className="tabs" style={{ margin: "0 24px 10px" }}>
        {(
          [
            ["mine", "Assigned to me"],
            ["starred", "Starred"],
            ["archived", "Archived"],
          ] as const
        ).map(([v, n]) => (
          <button key={v} className={`tab ${view === v ? "on" : ""}`} onClick={() => setView(v)}>
            {n}
          </button>
        ))}
      </div>
      {view === "mine" ? (
        <>
          <ViewToolbar k={k} group={false} />
          <div className="list-wrap">
            <ListView groups={groups} k={k} cols={["project", "status", "priority", "due"]} complete drag={false} />
          </div>
        </>
      ) : view === "starred" ? (
        <Starred />
      ) : (
        <Archived />
      )}
    </div>
  );
}

/** Tasks you starred, from every project you can see. */
function Starred() {
  const ws = live.ws?.id;
  const starred = useLiveStarredTasks(ws, isLive());
  const ts = isLive() ? (starred ?? []) : allTasks().filter((t) => t.fav);
  return (
    <div style={{ padding: "0 24px 24px" }}>
      {ts.length ? (
        <div className="panel" style={{ overflow: "hidden" }}>
          {ts.map((t) => (
            <MiniRow key={t.id} t={t} />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty icon="star" title="No starred tasks" text="Open a task and click the star to keep it here." />
        </div>
      )}
    </div>
  );
}

type ArchivedAt = { archivedAt?: number };

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

/** Archived tasks: restore them or delete them for good. Archived projects are restored from Settings → Projects. */
function Archived() {
  const ws = live.ws?.id;
  const archived = useLiveArchivedTasks(ws, isLive());
  const ts = isLive()
    ? (archived ?? [])
    : D()
        .tasks.filter((t) => t.archived && canSee(proj(t.project)) && !proj(t.project)?.archived)
        .sort((a, b) => ((b as ArchivedAt).archivedAt || 0) - ((a as ArchivedAt).archivedAt || 0));
  return (
    <div style={{ padding: "0 24px 24px" }}>
      {ts.length ? (
        <div className="panel" style={{ overflow: "hidden" }}>
          {ts.map((t) => {
            const at = (t as ArchivedAt).archivedAt;
            return (
              <div key={t.id} className="mini" style={{ minHeight: 52, cursor: "default", gap: 12 }}>
                <StIcon st={t.status} />
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="trunc" style={{ fontWeight: 500 }}>
                    {t.title}
                  </div>
                  <div className="faint trunc" style={{ fontSize: 12 }}>
                    {t.key} · {proj(t.project)?.name}
                  </div>
                </div>
                <span className="faint hide-m" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                  {at ? "Archived " + ago(at) : "Archived"}
                </span>
                <button className="btn btn-secondary btn-sm" onClick={() => restoreTask(t.id)}>
                  <Ic n="rotate-ccw" s={13} />
                  Restore
                </button>
                <button
                  className="ibtn ibtn-sm"
                  onClick={() => purgeTask(t.id)}
                  data-tip="Delete permanently"
                  aria-label="Delete permanently"
                  style={{ color: "var(--red)" }}
                >
                  <Ic n="trash-2" s={15} />
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="panel">
          <Empty
            icon="archive"
            title="No archived tasks"
            text="Archive finished or abandoned tasks to keep boards focused. They wait here until you restore them."
          />
        </div>
      )}
      <p className="faint" style={{ fontSize: 12, marginTop: 10 }}>
        Archived projects are restored from{" "}
        <button className="link" onClick={() => go("settings", { sec: "projects" })}>
          Settings → Projects
        </button>
        .
      </p>
    </div>
  );
}
