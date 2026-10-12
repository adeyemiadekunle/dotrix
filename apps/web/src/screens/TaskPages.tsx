// Task pages: the same views over every project you can see.
import { Ic } from "../core/icons";
import { newTask } from "../core/more";
import { go } from "../core/nav";
import { TODAY, dOff, diffD, parse } from "../core/utils";
import { D, S, allTasks, canSee, isOver, visibleProjects } from "../data/store";
import { LCOLS, ListView, MiniRow } from "../components/TaskList";
import { applyView, groupTasks, viewChange, viewOf, ViewToolbar, type Group } from "../shell/viewEngine";
import { Empty } from "../ui/helpers";
import { Board } from "../views/Board";
import { Calendar } from "../views/Calendar";
import { TlControls, Timeline } from "../views/Timeline";
import { ProjectCard } from "./Projects";

export function MyTasks() {
  const k = "mytasks";
  const v = viewOf(k);
  const mine = applyView(
    allTasks().filter((t) => t.assignee === D().me),
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
      <ViewToolbar k={k} group={false} />
      <div className="list-wrap">
        <ListView groups={groups} k={k} cols={["project", "status", "priority", "due"]} complete drag={false} />
      </div>
    </div>
  );
}

const TASKS_COLS = ["status", "assignee", "priority", "due", "project"];

export function Tasks() {
  const k = "tasks";
  const v = viewOf(k) as ReturnType<typeof viewOf> & { mode?: string };
  if (!v.mode || v.mode === "table") v.mode = "list";
  const ts = applyView(allTasks(), v);
  const right = (
    <div className="seg">
      {(
        [
          ["list", "List", "list"],
          ["board", "Board", "square-kanban"],
        ] as const
      ).map(([m, n, i]) => (
        <button key={m} className={v.mode === m ? "on" : ""} onClick={() => viewChange(k, (vv) => ((vv as typeof v).mode = m))}>
          <Ic n={i} s={13} />
          <span className="hide-m">{n}</span>
        </button>
      ))}
    </div>
  );
  return (
    <div className="page flush">
      <div className="ph">
        <div>
          <h1>Tasks</h1>
          <p>Every task across {visibleProjects().filter(canSee).length} projects.</p>
        </div>
        <div className="acts">
          <button className="btn btn-primary" onClick={() => newTask()}>
            <Ic n="plus" s={14} />
            New task
          </button>
        </div>
      </div>
      <ViewToolbar k={k} right={right} cols={v.mode === "list" && TASKS_COLS.map((c) => [c, LCOLS[c]![0]])} group={v.mode !== "board"} />
      {v.mode === "board" ? (
        <Board ts={ts} k={k} />
      ) : (
        <div className="list-wrap">
          <ListView groups={groupTasks(ts, v.group)} k={k} cols={TASKS_COLS} />
        </div>
      )}
    </div>
  );
}

export function CalendarPage() {
  const k = "cal";
  return (
    <div className="page flush">
      <div className="ph">
        <div>
          <h1>Calendar</h1>
          <p>Deadlines and events across every project.</p>
        </div>
        <div className="acts">
          <button className="btn btn-primary" onClick={() => newTask()}>
            <Ic n="plus" s={14} />
            New task
          </button>
        </div>
      </div>
      <ViewToolbar k={k} group={false} />
      <Calendar ts={applyView(allTasks(), viewOf(k))} k={k} events />
    </div>
  );
}

export function TimelinePage() {
  const k = "tl";
  if (!S.ui.tlWsInit) {
    S.ui.tlWsInit = true;
    S.ui.tlGroup = "project";
  }
  return (
    <div className="page flush">
      <div className="ph">
        <div>
          <h1>Timeline</h1>
          <p>Schedules, dependencies, and milestones across projects.</p>
        </div>
      </div>
      <ViewToolbar k={k} group={false} extra={<TlControls />} />
      <Timeline ts={applyView(allTasks(), viewOf(k))} k={k} p={null} />
    </div>
  );
}

export function Favorites() {
  const ps = visibleProjects().filter((p) => p.fav && canSee(p));
  const ts = allTasks().filter((t) => t.fav);
  return (
    <div className="page wide">
      <div className="ph">
        <div>
          <h1>Favorites</h1>
          <p>Projects and tasks you&apos;ve starred for quick access.</p>
        </div>
      </div>
      {!ps.length && !ts.length ? (
        <div className="panel">
          <Empty icon="star" title="No favorites yet" text="Star a project or task to pin it here.">
            <button className="btn btn-secondary btn-sm" onClick={() => go("projects")}>
              Browse projects
            </button>
          </Empty>
        </div>
      ) : (
        <>
          <h2 className="sec" style={{ marginBottom: 10 }}>
            Projects{" "}
            <span className="faint" style={{ fontWeight: 500 }}>
              {ps.length}
            </span>
          </h2>
          {ps.length ? (
            <div className="pgrid" style={{ marginBottom: 28 }}>
              {ps.map((p) => (
                <ProjectCard key={p.id} p={p} />
              ))}
            </div>
          ) : (
            <p className="faint" style={{ marginBottom: 28 }}>
              No favorite projects.
            </p>
          )}
          <h2 className="sec" style={{ marginBottom: 6 }}>
            Tasks{" "}
            <span className="faint" style={{ fontWeight: 500 }}>
              {ts.length}
            </span>
          </h2>
          {ts.length ? (
            <div className="panel" style={{ overflow: "hidden" }}>
              {ts.map((t) => (
                <MiniRow key={t.id} t={t} />
              ))}
            </div>
          ) : (
            <p className="faint">Open a task and click the star to add it here.</p>
          )}
        </>
      )}
    </div>
  );
}

// The workspace Activity page folded into Home.
