// The workspace activity feed: everything that changed, by people and agents.
import { SelectField } from "@dotrix/ui/components/select";
import { ActItem } from "../components/TaskList";
import { allowed } from "../core/can";
import { personal } from "../core/features";
import { Ic } from "../core/icons";
import { newProject, newTask } from "../core/more";
import { go } from "../core/nav";
import { dayBucket } from "../core/utils";
import { S, canSee, proj, render } from "../data/store";
import { useActivity, useMembers, useProjects } from "../data/lists";
import type { Activity as A } from "../data/types";
import { Empty } from "../ui/helpers";

export function ActivityPage() {
  const f = S.ui.actFilter;
  const whoF = S.ui.actWho;
  const solo = personal();
  const { items: members } = useMembers();
  const { items: projects } = useProjects();
  const visibleProjects = projects.filter((p) => canSee(p) && !p.archived);
  const allVisible = useActivity().items.filter((a) => !a.project || canSee(proj(a.project)));
  let as = allVisible;
  if (f !== "all")
    as = as.filter((a) =>
      f === "comments"
        ? a.verb.includes("comment")
        : f === "status"
          ? /moved|completed|reopened/.test(a.verb)
          : f === "projects"
            ? a.verb.includes("project")
            : f === "agents"
              ? !members.some((m) => m.id === a.by)
              : true,
    );
  if (!solo && whoF !== "all") as = as.filter((a) => a.by === whoF);
  const b: Record<string, A[]> = {};
  as.forEach((a) => (b[dayBucket(a.at)] ||= []).push(a));
  const filtered = f !== "all" || (!solo && whoF !== "all");

  return (
    <div className="page" style={{ maxWidth: 840 }}>
      <div className="ph">
        <div>
          <h1>Activity</h1>
          <p>
            {solo
              ? "Everything that's changed across your projects, by you and your agents."
              : "Everything that's changed across the workspace, by people and agents."}
          </p>
        </div>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <div className="seg">
          {[
            ["all", "All"],
            ["status", "Status changes"],
            ["comments", "Comments"],
            ["projects", "Projects"],
            ["agents", "Agents"],
          ].map(([k, n]) => (
            <button key={k} className={f === k ? "on" : ""} onClick={() => ((S.ui.actFilter = k!), render())}>
              {n}
            </button>
          ))}
        </div>
        {!solo && (
          <SelectField
            size="sm"
            aria-label="Filter by person"
            value={whoF}
            onValueChange={(value) => ((S.ui.actWho = value), render())}
            options={[{ value: "all", label: "Everyone" }, ...members.map((m) => ({ value: m.id, label: m.name }))]}
          />
        )}
      </div>
      {as.length ? (
        Object.entries(b).map(([k, list]) => (
          <div key={k}>
            <div className="day-h">{k}</div>
            <div className="feed lined">
              {list.map((a) => (
                <ActItem key={a.id} a={a} withProject />
              ))}
            </div>
          </div>
        ))
      ) : allVisible.length > 0 && filtered ? (
        <div className="panel">
          <Empty icon="list-filter" title="No matching activity" text="Nothing matches your current filter selection.">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                S.ui.actFilter = "all";
                S.ui.actWho = "all";
                render();
              }}
            >
              Show all activity
            </button>
          </Empty>
        </div>
      ) : (
        <div className="panel">
          <Empty icon="activity" title="No activity yet" text="Changes to tasks, documents, projects, and agent work will appear here as you build.">
            <div className="row" style={{ gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
              {visibleProjects.length > 0 ? (
                <>
                  <button className="btn btn-primary btn-sm" onClick={() => newTask()}>
                    <Ic n="plus" s={14} />
                    New task
                  </button>
                  <button className="btn btn-secondary btn-sm" onClick={() => go("projects")}>
                    Open projects
                  </button>
                </>
              ) : (
                allowed("projects:manage") && (
                  <button className="btn btn-primary btn-sm" onClick={newProject}>
                    <Ic n="folder-plus" s={14} />
                    Create project
                  </button>
                )
              )}
            </div>
          </Empty>
        </div>
      )}
    </div>
  );
}
