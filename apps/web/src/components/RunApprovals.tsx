// What an agent run waits on, from the API: changes to approve or reject, and checkpoints (a plan
// to continue, change, or stop). A run resumes once, with every decision, so with several changes
// waiting the choices are sent together when the last one is made.
import { useState } from "react";

import { useDecide, type Approval, type Decision, type Run } from "@/lib/agent";
import type { Scope } from "@/lib/issues";

import { Ic } from "../core/icons";
import { D, who } from "../data/store";
import { Diff } from "./Changes";

const KIND: Record<string, [string, string]> = {
  write_file: ["file-pen", "Edit document"],
  edit_file: ["file-pen", "Edit document"],
  create_issue: ["circle-plus", "Create issue"],
  update_issue: ["pencil", "Update issue"],
  comment_issue: ["message-square", "Comment"],
  checkpoint: ["map", "Plan"],
};
const CHECKPOINT = "checkpoint";
const kindOf = (tool: string): [string, string] => KIND[tool] ?? ["bot", tool.replaceAll("_", " ")];
const isFile = (a: Approval) => a.tool === "write_file" || a.tool === "edit_file";
const titleOf = (a: Approval) => (isFile(a) ? (a.target ?? "").replace(/^\/dotrix\//, "") : String(a.args?.title ?? a.target ?? a.action));
const shown = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

type Choice = { decision: Decision["decision"]; reason: string };

function Decided({ a }: { a: Approval }) {
  const ok = a.status === "approved";
  return (
    <span className={`badge ${ok ? "green" : "red"}`}>
      <Ic n={ok ? "check" : "x"} s={11} />
      {a.tool === CHECKPOINT ? (ok ? "Continued" : "Stopped") : ok ? "Approved" : "Rejected"}
      {a.decided_by_id && a.decided_by_id !== D().me ? ` by ${who(a.decided_by_id)?.name ?? "someone"}` : ""}
    </span>
  );
}

function ChangeCard({ a, choice, onChoose, busy }: { a: Approval; choice?: Choice; onChoose: (c: Choice | undefined) => void; busy: boolean }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(true);
  const [icon, label] = kindOf(a.tool);
  const pending = a.status === "pending";
  const fields = Object.entries(a.args ?? {}).filter(([k, v]) => k !== "content" && v !== null && v !== "" && !(Array.isArray(v) && !v.length));
  return (
    <div className="change">
      <div className="change-h">
        <Ic n={icon} s={14} />
        <span className="muted">{label}</span>
        <b className={`trunc ${isFile(a) ? "mono" : ""}`} style={{ fontWeight: 500, fontSize: isFile(a) ? 12 : undefined }}>
          {titleOf(a)}
        </b>
        <span className="sp" />
        {!pending && <Decided a={a} />}
        <button className="ibtn ibtn-xs" onClick={() => setOpen(!open)} aria-label={open ? "Hide details" : "Show details"} aria-expanded={open}>
          <Ic n={open ? "chevron-up" : "chevron-down"} s={13} />
        </button>
      </div>
      {open && (a.diff || fields.length > 0) && (
        <div className="change-b">
          {a.diff ? (
            <Diff diff={a.diff} />
          ) : (
            <dl className="kv" style={{ margin: 0 }}>
              {fields.map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k.replaceAll("_", " ")}</dt>
                  <dd>{shown(v)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}
      {!pending && a.reason && (
        <div className="change-b muted" style={{ borderTop: "1px solid var(--divider)" }}>
          Why: {a.reason}
        </div>
      )}
      {pending && (
        <div className="change-f">
          {choice ? (
            <>
              <span className="faint" style={{ fontSize: 12 }}>
                {choice.decision === "approve" ? "You approve this" : "You reject this"}; sent with the others
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-ghost" onClick={() => onChoose(undefined)} disabled={busy}>
                Undo
              </button>
            </>
          ) : rejecting ? (
            <>
              <input
                className="input"
                style={{ height: 28, flex: 1 }}
                placeholder="Why? The agent learns from it (optional)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onChoose({ decision: "reject", reason })}
                autoFocus
                aria-label="Reason"
              />
              <button className="btn btn-sm btn-ghost" onClick={() => setRejecting(false)}>
                Cancel
              </button>
              <button className="btn btn-sm btn-danger" onClick={() => onChoose({ decision: "reject", reason })} disabled={busy}>
                Reject
              </button>
            </>
          ) : (
            <>
              <span className="faint" style={{ fontSize: 12 }}>
                Waiting for your decision
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-secondary" onClick={() => setRejecting(true)} disabled={busy}>
                Reject
              </button>
              <button className="btn btn-sm btn-primary" onClick={() => onChoose({ decision: "approve", reason: "" })} disabled={busy}>
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

function Checkpoint({ a, onAnswer, busy }: { a: Approval; onAnswer: (c: Choice) => void; busy: boolean }) {
  const [note, setNote] = useState("");
  const pending = a.status === "pending";
  const plan = a.args?.plan;
  const steps = Array.isArray(plan) ? plan.map(shown) : typeof plan === "string" ? plan.split("\n").filter(Boolean) : [];
  return (
    <div className="change">
      <div className="change-h">
        <Ic n="map" s={14} />
        <span className="muted">Plan</span>
        <b className="trunc" style={{ fontWeight: 500 }}>
          {String(a.args?.title ?? "Before the large part of the job")}
        </b>
        <span className="sp" />
        {!pending && <Decided a={a} />}
      </div>
      {steps.length > 0 && (
        <div className="change-b">
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            {steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </div>
      )}
      {pending && (
        <div className="change-f">
          <input
            className="input"
            style={{ height: 28, flex: 1 }}
            placeholder="Change something? Say what, then Change plan"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && note.trim() && onAnswer({ decision: "steer", reason: note.trim() })}
            aria-label="What to change"
          />
          <button className="btn btn-sm btn-secondary" disabled={busy || !note.trim()} onClick={() => onAnswer({ decision: "steer", reason: note.trim() })}>
            Change plan
          </button>
          <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => onAnswer({ decision: "reject", reason: "" })}>
            Stop
          </button>
          <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => onAnswer({ decision: "approve", reason: "" })}>
            Continue
          </button>
        </div>
      )}
    </div>
  );
}

/** A run's changes and checkpoints, with "Approve all" when several changes wait. */
export function RunApprovals({ run, scope }: { run: Run; scope: Scope | undefined }) {
  const decide = useDecide(scope);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const approvals = run.approvals ?? [];
  if (!approvals.length) return null;
  const waiting = approvals.filter((a) => a.status === "pending" && a.tool !== CHECKPOINT);
  const send = (decisions: Record<string, Choice>) =>
    decide.mutate(
      { runId: run.id, decisions: Object.entries(decisions).map(([id, c]) => ({ approval_id: id, decision: c.decision, reason: c.reason.trim() || null })) },
      { onSettled: () => setChoices({}) },
    );
  const choose = (a: Approval, c: Choice | undefined) => {
    const next = { ...choices };
    if (c) next[a.id] = c;
    else delete next[a.id];
    if (waiting.every((w) => next[w.id])) send(next);
    else setChoices(next);
  };
  const all = (decision: "approve" | "reject") => send(Object.fromEntries(waiting.map((w) => [w.id, { decision, reason: "" }])));
  return (
    <div style={{ marginTop: 4 }}>
      {waiting.length > 0 && (
        <div className="faint" style={{ fontSize: 12, margin: "4px 0" }}>
          {waiting.length === 1 ? "1 change waits for your approval" : `${waiting.length} changes wait for your approval`}
        </div>
      )}
      {approvals.map((a) =>
        a.tool === CHECKPOINT ? (
          <Checkpoint key={a.id} a={a} busy={decide.isPending} onAnswer={(c) => send({ [a.id]: c })} />
        ) : (
          <ChangeCard key={a.id} a={a} choice={choices[a.id]} busy={decide.isPending} onChoose={(c) => choose(a, c)} />
        ),
      )}
      {waiting.length > 1 && (
        <div className="row" style={{ justifyContent: "flex-end", gap: 6, marginTop: 8 }}>
          <button className="btn btn-sm btn-ghost" onClick={() => all("reject")} disabled={decide.isPending}>
            Reject all
          </button>
          <button className="btn btn-sm btn-secondary" onClick={() => all("approve")} disabled={decide.isPending}>
            <Ic n="check-check" s={13} />
            Approve all {waiting.length}
          </button>
        </div>
      )}
    </div>
  );
}
