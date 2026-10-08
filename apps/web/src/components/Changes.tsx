// An agent's proposed changes (a document diff, an issue's fields) and checkpoints (a plan to
// continue, change, or stop), the same in Chat and Notifications.
import { useState } from "react";

import { answerCheckpoint, decideAll, decideChange } from "../core/agents";
import { Ic } from "../core/icons";
import { D, who } from "../data/store";
import type { ChatMessage, ProposedChange } from "../data/types";

export function Diff({ diff }: { diff: string }) {
  return (
    <div className="diff">
      {diff.split("\n").map((l, i) => (
        <div key={i} className={l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : ""}>
          {l || " "}
        </div>
      ))}
    </div>
  );
}

const KIND: Record<ProposedChange["kind"], [string, string]> = {
  write_file: ["file-pen", "Edit document"],
  create_issue: ["circle-plus", "Create issue"],
  update_issue: ["pencil", "Update issue"],
  comment: ["message-square", "Comment"],
  checkpoint: ["map", "Plan"],
};

function Decided({ ch }: { ch: ProposedChange }) {
  const ok = ch.status === "approved";
  return (
    <span className={`badge ${ok ? "green" : "red"}`}>
      <Ic n={ok ? "check" : "x"} s={11} />
      {ch.kind === "checkpoint" ? (ok ? "Continued" : "Stopped") : ok ? "Approved" : "Rejected"}
      {ch.decidedBy && ch.decidedBy !== D().me ? ` by ${who(ch.decidedBy)?.name}` : ""}
    </span>
  );
}

export function ChangeCard({ ch }: { ch: ProposedChange }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(true);
  if (ch.kind === "checkpoint") return <Checkpoint ch={ch} />;
  const [icon, label] = KIND[ch.kind];
  const pending = ch.status === "pending";
  return (
    <div className="change">
      <div className="change-h">
        <Ic n={icon} s={14} />
        <span className="muted">{label}</span>
        <b className={`trunc ${ch.kind === "write_file" ? "mono" : ""}`} style={{ fontWeight: 500, fontSize: ch.kind === "write_file" ? 12 : undefined }}>
          {ch.title}
        </b>
        <span className="sp" />
        {!pending && <Decided ch={ch} />}
        <button className="ibtn ibtn-xs" onClick={() => setOpen(!open)} aria-label={open ? "Hide details" : "Show details"} aria-expanded={open}>
          <Ic n={open ? "chevron-up" : "chevron-down"} s={13} />
        </button>
      </div>
      {open && (ch.diff || ch.fields) && (
        <div className="change-b">
          {ch.diff ? (
            <Diff diff={ch.diff} />
          ) : (
            <dl className="kv" style={{ margin: 0 }}>
              {Object.entries(ch.fields!).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
      {!pending && ch.reason && (
        <div className="change-b muted" style={{ borderTop: "1px solid var(--divider)" }}>
          Why: {ch.reason}
        </div>
      )}
      {pending && (
        <div className="change-f">
          {rejecting ? (
            <>
              <input className="input" style={{ height: 28, flex: 1 }} placeholder="Why? The agent learns from it (optional)" value={reason} onChange={(e) => setReason(e.target.value)} onKeyDown={(e) => e.key === "Enter" && decideChange(ch.id, false, reason)} autoFocus aria-label="Reason" />
              <button className="btn btn-sm btn-ghost" onClick={() => setRejecting(false)}>
                Cancel
              </button>
              <button className="btn btn-sm btn-danger" onClick={() => decideChange(ch.id, false, reason)}>
                Reject
              </button>
            </>
          ) : (
            <>
              <span className="faint" style={{ fontSize: 12 }}>
                Waiting for your decision
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-secondary" onClick={() => setRejecting(true)}>
                Reject
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => decideChange(ch.id, true)}>
                <Ic n="check" s={13} />
                Approve
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Checkpoint({ ch }: { ch: ProposedChange }) {
  const [steering, setSteering] = useState(false);
  const [note, setNote] = useState("");
  const pending = ch.status === "pending";
  return (
    <div className="change" style={pending ? { borderColor: "var(--accent-line)" } : undefined}>
      <div className="change-h">
        <Ic n="map" s={14} />
        <b style={{ fontWeight: 500 }}>{ch.title}</b>
        <span className="sp" />
        {!pending && <Decided ch={ch} />}
      </div>
      <div className="change-b">
        <ol style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          {ch.plan?.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        {!pending && ch.reason && <div className="muted" style={{ marginTop: 6 }}>Changed: {ch.reason}</div>}
      </div>
      {pending && (
        <div className="change-f">
          {steering ? (
            <>
              <input className="input" style={{ height: 28, flex: 1 }} placeholder="What should change?" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => e.key === "Enter" && note.trim() && answerCheckpoint(ch.id, "steer", note)} autoFocus aria-label="Changes to the plan" />
              <button className="btn btn-sm btn-ghost" onClick={() => setSteering(false)}>
                Cancel
              </button>
              <button className="btn btn-sm btn-primary" disabled={!note.trim()} onClick={() => answerCheckpoint(ch.id, "steer", note)}>
                Update the plan
              </button>
            </>
          ) : (
            <>
              <span className="faint" style={{ fontSize: 12 }}>
                The agent paused before the expensive part
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-ghost" onClick={() => answerCheckpoint(ch.id, "stop")}>
                Stop
              </button>
              <button className="btn btn-sm btn-secondary" onClick={() => setSteering(true)}>
                Change the plan
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => answerCheckpoint(ch.id, "continue")}>
                Continue
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/** A reply's changes, with "Approve all" when several wait. */
export function Changes({ msg }: { msg: ChatMessage }) {
  const ch = msg.changes ?? [];
  const waiting = ch.filter((c) => c.status === "pending" && c.kind !== "checkpoint").length;
  if (!ch.length) return null;
  return (
    <div style={{ marginTop: 4 }}>
      {ch.map((c) => (
        <ChangeCard key={c.id} ch={c} />
      ))}
      {waiting > 1 && (
        <div className="row" style={{ justifyContent: "flex-end", gap: 6, marginTop: 8 }}>
          <button className="btn btn-sm btn-ghost" onClick={() => decideAll(msg, false)}>
            Reject all
          </button>
          <button className="btn btn-sm btn-secondary" onClick={() => decideAll(msg, true)}>
            <Ic n="check-check" s={13} />
            Approve all {waiting}
          </button>
        </div>
      )}
    </div>
  );
}
