// The workspace activity feed: everything that changed, by people and agents.
import { ActItem } from "../components/TaskList";
import { dayBucket } from "../core/utils";
import { D, S, canSee, proj, render } from "../data/store";
import { isLive, live } from "../data/live";
import { useLiveWorkspaceActivity } from "../../lib/workspace-data";
import type { Activity as A } from "../data/types";
import { Empty } from "../ui/helpers";

export function ActivityPage() {
  const f = S.ui.actFilter;
  const whoF = S.ui.actWho;
  const liveFeed = useLiveWorkspaceActivity(live.ws?.id, isLive());
  let as = (isLive() ? (liveFeed ?? []) : D().activity).filter((a) => !a.project || canSee(proj(a.project)));
  if (f !== "all")
    as = as.filter((a) =>
      f === "comments"
        ? a.verb.includes("comment")
        : f === "status"
          ? /moved|completed|reopened/.test(a.verb)
          : f === "projects"
            ? a.verb.includes("project")
            : f === "agents"
              ? !D().members.some((m) => m.id === a.by)
              : true,
    );
  if (whoF !== "all") as = as.filter((a) => a.by === whoF);
  const b: Record<string, A[]> = {};
  as.forEach((a) => (b[dayBucket(a.at)] ||= []).push(a));
  return (
    <div className="page" style={{ maxWidth: 820 }}>
      <div className="ph">
        <div>
          <h1>Activity</h1>
          <p>Everything that&apos;s changed across the workspace, by people and agents.</p>
        </div>
      </div>
      <div className="row" style={{ gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
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
        <select
          className="select"
          style={{ height: 26, width: "auto", fontSize: 12 }}
          value={whoF}
          onChange={(e) => ((S.ui.actWho = e.target.value), render())}
          aria-label="Filter by person"
        >
          <option value="all">Everyone</option>
          {D().members.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
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
      ) : (
        <Empty icon="activity" title="No activity yet" text="Changes to tasks and projects will appear here." />
      )}
    </div>
  );
}
