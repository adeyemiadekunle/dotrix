// Lessons the agents could learn from people's decisions. Rejecting an agent's proposed change or
// dismissing a finding, with a reason, proposes a lesson; a project manager accepts it (in their own
// words if they edit it first) and it lands in agent-rules/lessons/<agent>.md, which the agent reads
// on every run. Declined lessons stay listed, so it's clear they were considered.
import { useState } from "react";

import { useAcceptLesson, useDeclineLesson, useLessons, type Lesson } from "../../lib/lessons";
import { isLive, live } from "../data/live";
import { D, who } from "../data/store";
import type { Project } from "../data/types";
import { Ic } from "../core/icons";
import { ago } from "../core/utils";
import { Av, Empty } from "../ui/helpers";
import { toast } from "../ui/toast";

const agentName = (h: string) => D().agents.find((a) => a.handle === h)?.name ?? h;
const personName = (id: string | null | undefined) => who(id)?.name ?? "someone";

function Proposed({ p, l }: { p: Project; l: Lesson }) {
  const scope = isLive() && live.ws ? { workspaceId: live.ws.id, projectId: p.id } : undefined;
  const accept = useAcceptLesson(scope);
  const decline = useDeclineLesson(scope);
  const [text, setText] = useState(l.text);
  const busy = accept.isPending || decline.isPending;
  return (
    <div className="panel" style={{ padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <Av id={l.proposed_by_id ?? undefined} cls="sm" />
        <b style={{ fontSize: 13 }}>{agentName(l.agent)}</b>
        <span className="faint" style={{ fontSize: 12 }}>
          {l.source === "rejection" ? "a change was rejected" : "an item was dismissed"} by {personName(l.proposed_by_id)} · {ago(Date.parse(l.created_at))}
        </span>
      </div>
      <textarea
        className="input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={600}
        rows={3}
        style={{ width: "100%", resize: "vertical", fontSize: 13 }}
        aria-label="Lesson the agent will read"
      />
      <div className="faint" style={{ fontSize: 12, marginTop: 6 }}>
        Reason: “{l.reason}”
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button
          className="btn btn-sm"
          disabled={busy || !text.trim()}
          onClick={() =>
            accept.mutate(
              { lessonId: l.id, body: { text: text.trim() === l.text ? undefined : text.trim() } },
              { onSuccess: () => toast(`Lesson added to ${agentName(l.agent)}'s rules`) },
            )
          }
        >
          <Ic n="check" s={13} /> Teach {agentName(l.agent)}
        </button>
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => decline.mutate(l.id, { onSuccess: () => toast("Lesson declined") })}>
          Decline
        </button>
      </div>
    </div>
  );
}

function Decided({ l }: { l: Lesson }) {
  return (
    <div className="panel" style={{ padding: 14, opacity: 0.85 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className="pillbtn bordered"
          style={{
            height: 22,
            color: l.status === "accepted" ? "var(--green)" : "var(--faint)",
          }}
        >
          {l.status === "accepted" ? <Ic n="check" s={12} /> : <Ic n="x" s={12} />}
          {l.status === "accepted" ? "Taught" : "Declined"}
        </span>
        <b style={{ fontSize: 13 }}>{agentName(l.agent)}</b>
        <span className="faint" style={{ fontSize: 12 }}>
          by {personName(l.decided_by_id)}
          {l.decided_at ? ` · ${ago(Date.parse(l.decided_at))}` : ""}
        </span>
      </div>
      <p className="faint" style={{ fontSize: 13, marginTop: 8 }}>
        {l.text}
      </p>
    </div>
  );
}

export function Lessons({ p, lead }: { p: Project; lead?: React.ReactNode }) {
  const scope = isLive() && live.ws ? { workspaceId: live.ws.id, projectId: p.id } : undefined;
  const lessons = useLessons(scope);
  const all = lessons.data ?? [];
  const proposed = all.filter((l) => l.status === "proposed");
  const decided = all.filter((l) => l.status !== "proposed");
  return (
    <>
      <div className="toolbar">{lead}</div>
      <div className="page wide" style={{ paddingTop: 16 }}>
        <div style={{ display: "grid", gap: 12, maxWidth: 720 }}>
          {lessons.isLoading ? (
            <div className="faint" style={{ padding: 24, textAlign: "center" }}>
              Loading…
            </div>
          ) : !all.length ? (
            <Empty
              icon="book-open"
              title="No lessons yet"
              text="When an agent's change is rejected or a finding is dismissed with a reason, it's proposed here. Accept one and the agent reads it on every run from agent-rules/lessons/."
            />
          ) : (
            <>
              {proposed.map((l) => (
                <Proposed key={l.id} p={p} l={l} />
              ))}
              {decided.length ? (
                <div className="faint" style={{ fontSize: 12, marginTop: 8, textTransform: "uppercase", letterSpacing: 0.6 }}>
                  Decided
                </div>
              ) : null}
              {decided.map((l) => (
                <Decided key={l.id} l={l} />
              ))}
            </>
          )}
        </div>
      </div>
    </>
  );
}
