// dotrix's workspace Chat in Gr8r's design (Gr8r has none): conversations grouped by project (and
// "Across projects"), a new chat with project, agent, and model; replies with what the agent did
// and the changes it proposes; and the Coding tab, coding sessions with their turns.
// URL: ?project=KEY&thread=ID, ?tab=coding&session=ID, ?q= (start with a question), ?agent=.
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { decideCoding, followUp, newThread, sendChat, stopCoding } from "../core/agents";
import { openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { MOD, ago, greeting } from "../core/utils";
import { D, S, canSee, me, pColor, proj, projByKey, render, task, visibleProjects, who } from "../data/store";
import type { CodingSession, Thread } from "../data/types";
import { Markdown } from "@/components/markdown";
import { Changes } from "../components/Changes";
import { openDocument } from "./Knowledge";
import { Av, Empty, PIcon } from "../ui/helpers";
import { moodOf } from "../core/presence";
import { Face } from "../ui/face";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const MODELS = ["Gemini 3.8 Flash", "Claude Sonnet 5.5", "Claude Opus 5.5", "GPT-5.5"];
const agentName = (h: string) => D().agents.find((a) => a.handle === h)?.name ?? h;

const SUGGESTIONS = [
  ["sparkles", "Summarise the project"],
  ["history", "What changed since yesterday?"],
  ["compass", "What should we build next?"],
  ["list-tree", "Turn the requirements into stories"],
];
const ACROSS = [
  ["layers", "Summarise all my projects"],
  ["triangle-alert", "What's at risk this week?"],
];

function open(search: string) {
  go("chat", {}, { search });
}

/* ---------- the list ---------- */

function ThreadRow({ th, on }: { th: Thread; on: boolean }) {
  const waiting = th.messages.some((m) => m.changes?.some((c) => c.status === "pending"));
  return (
    <button className={`sitem ${on ? "on" : ""}`} style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start" }} onClick={() => open(`thread=${th.id}`)}>
      <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
        <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
          {th.title}
        </span>
        <span className="faint" style={{ fontSize: 11.5 }}>
          {agentName(th.agent)} · {ago(th.at)}
        </span>
      </span>
      {waiting && <span className="sdot" style={{ background: "var(--amber)", marginTop: 6 }} aria-label="Waiting for a decision" />}
    </button>
  );
}

function Group({ title, icon, color, children, onNew }: { title: string; icon?: React.ReactNode; color?: string; children: React.ReactNode; onNew: () => void }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div className="row" style={{ padding: "0 8px", height: 26, fontSize: 11.5, color: "var(--text-3)", fontWeight: 500 }}>
        {icon ?? <span className="pdot" style={css({ "--c": color ?? "var(--text-3)", width: 7, height: 7 })} />}
        <span className="grow trunc">{title}</span>
        <button className="ibtn ibtn-xs" onClick={onNew} data-tip="New chat here" aria-label={`New chat in ${title}`}>
          <Ic n="plus" s={13} />
        </button>
      </div>
      {children}
    </div>
  );
}

const STATUS: Record<CodingSession["status"], [string, string]> = {
  awaiting_approval: ["Waiting for approval", "amber"],
  queued: ["Queued", ""],
  running: ["Working", "accent"],
  pr_opened: ["PR opened", "green"],
  no_changes: ["No changes", ""],
  failed: ["Failed", "red"],
  stopped: ["Stopped", ""],
  rejected: ["Rejected", "red"],
};
const toolName = (t: CodingSession["tool"]) => (t === "codex" ? "Codex" : "Claude Code");

function SessionRow({ cs, on }: { cs: CodingSession; on: boolean }) {
  const t = task(cs.task);
  const [label, c] = STATUS[cs.status];
  return (
    <button className={`sitem ${on ? "on" : ""}`} style={{ height: "auto", padding: "6px 8px", alignItems: "flex-start" }} onClick={() => open(`tab=coding&session=${cs.id}`)}>
      <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
        <span className="trunc" style={{ display: "block", fontWeight: on ? 500 : 400 }}>
          <span className="mono faint" style={{ fontSize: 11 }}>
            {t?.key}
          </span>{" "}
          {t?.title}
        </span>
        <span className="row faint" style={{ fontSize: 11.5, gap: 6 }}>
          {toolName(cs.tool)} · {ago(cs.at)}
          {cs.pr && <span>· PR #{cs.pr.number}</span>}
        </span>
      </span>
      <span className={`badge ${c}`} style={{ marginTop: 2 }}>
        {label}
      </span>
    </button>
  );
}

/* ---------- a conversation ---------- */

/** Issue keys a reply names, and documents it read: chips that open them. */
function refsOf(th: Thread, text: string, activity: string[] = []): { tasks: string[]; docs: string[] } {
  const tasks = [...new Set(text.match(/\b[A-Z]{2,6}-\d+\b/g) ?? [])].filter((k) => D().tasks.some((t) => t.key === k)).slice(0, 4);
  const p = proj(th.project);
  const docs = p
    ? [...new Set(activity.flatMap((a) => a.match(/[\w./-]+\.md\b/g) ?? []))]
        .map((n) => D().knowledge.find((f) => f.project === p.id && (f.path === n || f.path.endsWith(`/${n}`)))?.path)
        .filter((x): x is string => Boolean(x))
        .slice(0, 4)
    : [];
  return { tasks, docs };
}

function Message({ th, i }: { th: Thread; i: number }) {
  const m = th.messages[i]!;
  const w = who(m.by);
  const agent = m.role === "agent" ? D().agents.find((a) => a.handle === m.by) : null;
  const [openSteps, setOpenSteps] = useState(false);
  const refs = agent ? refsOf(th, m.text, m.activity) : { tasks: [], docs: [] };
  const p = proj(th.project);
  const admin = me()?.role === "Owner" || me()?.role === "Admin";
  return (
    <div className={`chat-msg ${m.role}`}>
      {agent ? <Face c={agent.c} size={26} mood="idle" /> : <Av id={m.by} cls="md" tip={false} />}
      <div className="body">
        <div className="who">
          <b>{m.by === D().me ? "You" : w?.name}</b>
          {agent && <span className="role">{agent.role}</span>}
          <time>{ago(m.at)}</time>
          {m.tokens && admin && <span className="faint">{(m.tokens / 1000).toFixed(1)}k tokens</span>}
        </div>
        {m.activity && m.activity.length > 0 && (
          <div className="chat-steps">
            <button className="chat-steps-h" onClick={() => setOpenSteps(!openSteps)} aria-expanded={openSteps}>
              <Ic n="chevron-right" s={12} cls={`chev ${openSteps ? "open" : ""}`} />
              <Ic n="sparkles" s={12} />
              Worked through {m.activity.length} step{m.activity.length > 1 ? "s" : ""}
            </button>
            {openSteps && (
              <ul>
                {m.activity.map((a) => (
                  <li key={a}>
                    <Ic n="check" s={11} />
                    {a}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {m.role === "user" ? (
          <div className="said">{m.text}</div>
        ) : (
          <div className="md">
            <Markdown>{m.text}</Markdown>
          </div>
        )}
        {(refs.tasks.length > 0 || refs.docs.length > 0) && (
          <div className="chat-refs">
            {refs.tasks.map((k) => (
              <button key={k} className="ref" onClick={() => openTask(D().tasks.find((t) => t.key === k)!.id)}>
                <Ic n="square-check" s={12} />
                {k}
              </button>
            ))}
            {p &&
              refs.docs.map((d) => (
                <button key={d} className="ref" onClick={() => openDocument(p, d)}>
                  <Ic n="file-text" s={12} />
                  {d}
                </button>
              ))}
          </div>
        )}
        <Changes msg={m} />
      </div>
    </div>
  );
}

const MODELS_ICON = "cpu";

function Composer({ placeholder, onSend, agent, setAgent, model, setModel, autoFocus, initial = "", context }: { placeholder: string; onSend: (text: string, agent: string) => void; agent: string; setAgent: (a: string) => void; model?: string; setModel?: (m: string) => void; autoFocus?: boolean; initial?: string; context?: string }) {
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const a = D().agents.find((x) => x.handle === agent);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const send = () => {
    let q = text.trim();
    if (!q || S.ui.offline) return;
    // "@vega …" (or its handle, "@research") picks the agent
    const m = q.match(/^@(\w+)\s+/);
    let pick = agent;
    const named = m && D().agents.find((x) => x.handle === m[1] || x.name.toLowerCase() === m[1]!.toLowerCase());
    if (m && named) {
      pick = named.handle;
      q = q.slice(m[0].length);
      setAgent(pick);
    }
    onSend(q, pick);
    setText("");
  };
  return (
    <div className="cbox">
      <textarea
        ref={ref}
        rows={2}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        aria-label="Message"
      />
      <div className="cbox-row">
        {context && (
          <span className="cpill" data-tip="What the agents read: the project's documents and board">
            <Ic n="at-sign" s={12} />
            {context}
          </span>
        )}
        <label className="cpill pick">
          {a && <Face c={a.c} size={16} mood="idle" />}
          <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="Agent">
            {D().agents.map((x) => (
              <option key={x.handle} value={x.handle}>
                {x.name} · {x.role}
              </option>
            ))}
          </select>
          <Ic n="chevron-down" s={11} />
        </label>
        {setModel ? (
          <label className="cpill pick">
            <Ic n={MODELS_ICON} s={12} />
            <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
              {MODELS.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
            <Ic n="chevron-down" s={11} />
          </label>
        ) : (
          model && (
            <span className="cpill" data-tip="The model is fixed once a conversation starts">
              <Ic n={MODELS_ICON} s={12} />
              {model}
            </span>
          )
        )}
        <span className="sp" />
        <button className="cbox-send" onClick={send} disabled={!text.trim() || S.ui.offline} aria-label="Send">
          <Ic n="arrow-up" s={14} />
        </button>
      </div>
    </div>
  );
}

function Conversation({ th }: { th: Thread }) {
  const p = proj(th.project);
  const busy = S.ui.chatBusy === th.id;
  const end = useRef<HTMLDivElement>(null);
  const [agent, setAgent] = useState(th.agent);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [th.id, th.messages.length, busy]);
  return (
    <>
      <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
        <button className="ibtn ibtn-sm" onClick={() => open(p ? `project=${p.key}` : "")} aria-label="Back to conversations">
          <Ic n="arrow-left" s={15} />
        </button>
        <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
          {th.title}
        </b>
        <span className="sp" />
        {p ? (
          <button className="pillbtn" onClick={() => go("project", { id: p.key, tab: "overview" })}>
            <PIcon p={p} s={12} />
            {p.name}
          </button>
        ) : (
          <span className="pillbtn">
            <Ic n="layers" s={13} />
            {(th.projects ?? []).map((id) => proj(id)?.name).join(", ") || "Across projects"}
          </span>
        )}
        <span className="chat-faces hide-m" aria-label="Agents in this conversation">
          {[...new Set(th.messages.filter((x) => x.role === "agent").map((x) => x.by))].map((h) => {
            const ag = D().agents.find((x) => x.handle === h);
            return ag ? (
              <span key={h} data-tip={`${ag.name} · ${ag.role}`}>
                <Face c={ag.c} size={20} mood={moodOf(h)} />
              </span>
            ) : null;
          })}
        </span>
      </div>
      <div className="chat-scroll">
        <div className="chat-col">
          {th.messages.map((_, i) => (
            <Message key={th.messages[i]!.id} th={th} i={i} />
          ))}
          {busy && (
            <div className="chat-msg">
              <Face c={D().agents.find((a) => a.handle === agent)?.c ?? "#E0A92E"} size={26} mood="working" />
              <div className="body">
                <div className="who">
                  <b>{agentName(agent)}</b>
                  <span className="role">{D().agents.find((a) => a.handle === agent)?.role}</span>
                </div>
                <div className="row muted" style={{ gap: 8, fontSize: 12.5, marginTop: 6 }}>
                  <span className="chat-typing">
                    <i />
                    <i />
                    <i />
                  </span>
                  {agentName(agent)} is reading the project's documents…
                </div>
              </div>
            </div>
          )}
          <div ref={end} />
        </div>
      </div>
      <div className="chat-input">
        <Composer placeholder={`Ask ${agentName(agent)}, or type @ to pick an agent`} agent={agent} setAgent={setAgent} model={th.model} context={p?.name ?? "Across projects"} onSend={(q, a) => sendChat(th, q, a)} autoFocus />
        {!th.project && (
          <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
            <Ic n="lock" s={11} /> Across projects the agents only read; for a change they'll say which project's chat to ask in.
          </div>
        )}
      </div>
    </>
  );
}

function NewChat({ projectKey, across, q, agent0 }: { projectKey: string | null; across: boolean; q: string; agent0: string | null }) {
  const ps = visibleProjects().filter((p) => canSee(p) && !p.archived);
  const [pid, setPid] = useState<string>(across ? "" : (projByKey(projectKey ?? "")?.id ?? ps[0]?.id ?? ""));
  const [picked, setPicked] = useState<string[]>(ps.slice(0, 3).map((p) => p.id));
  const [agent, setAgent] = useState(agent0 ?? S.ui.chatAgent);
  const [model, setModel] = useState(S.ui.chatModel);
  const start = (text: string, a: string) => {
    S.ui.chatAgent = a;
    S.ui.chatModel = model;
    const th = pid ? newThread(pid, a, model, text) : newThread(null, a, model, text, picked);
    if (th) open(`thread=${th.id}`);
  };
  const sugg = pid ? SUGGESTIONS : ACROSS;
  return (
    <div className="chat-scroll" style={{ display: "flex", alignItems: "center" }}>
      <div className="chat-col" style={{ paddingTop: 40 }}>
        <h1 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px" }}>
          {greeting()}, {me()?.name.split(" ")[0]}
        </h1>
        <p className="muted" style={{ margin: "0 0 18px" }}>
          Ask the agents about a project: they read its documents and board, and propose changes for you to approve.
        </p>
        <div className="row" style={{ gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
          <span className="faint" style={{ fontSize: 12 }}>
            About
          </span>
          <select className="select" style={{ height: 26, width: "auto", fontSize: 12 }} value={pid} onChange={(e) => setPid(e.target.value)} aria-label="Project">
            {ps.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
            <option value="">Across projects</option>
          </select>
          {!pid &&
            ps.map((p) => (
              <label key={p.id} className="badge" style={{ cursor: "pointer", gap: 5 }}>
                <input type="checkbox" checked={picked.includes(p.id)} onChange={() => setPicked(picked.includes(p.id) ? picked.filter((x) => x !== p.id) : [...picked, p.id])} />
                {p.name}
              </label>
            ))}
        </div>
        <Composer key={q} placeholder="Ask anything, or type @ to pick an agent" agent={agent} setAgent={setAgent} model={model} setModel={setModel} context={proj(pid)?.name ?? "Across projects"} onSend={start} autoFocus initial={q} />
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 14 }}>
          {sugg.map(([i, s]) => (
            <button key={s} className="btn btn-secondary btn-sm" onClick={() => start(s!, agent)} disabled={!pid && !picked.length}>
              <Ic n={i!} s={13} />
              {s}
            </button>
          ))}
        </div>
        <div className="eyebrow" style={{ margin: "28px 0 6px" }}>
          The agents
        </div>
        <div className="panel" style={{ overflow: "hidden" }}>
          {D().agents.map((a) => (
            <button key={a.handle} className="mini" style={{ width: "100%" }} onClick={() => setAgent(a.handle)}>
              <Face c={a.c} size={26} mood={moodOf(a.handle)} />
              <span className="tt" style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                <b style={{ fontWeight: 500 }}>{a.name}</b> <span className="muted" style={{ fontSize: 12 }}>{a.role}</span>{" "}
                <span className="faint" style={{ fontSize: 12 }}>
                  {a.desc}
                </span>
              </span>
              {agent === a.handle && <Ic n="check" s={14} />}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- a coding session ---------- */

function Session({ cs }: { cs: CodingSession }) {
  const t = task(cs.task)!;
  const p = proj(cs.project)!;
  const [ask, setAsk] = useState("");
  const [label, c] = STATUS[cs.status];
  const busy = cs.status === "awaiting_approval" || cs.status === "running" || cs.status === "queued";
  return (
    <>
      <div className="row" style={{ height: 46, padding: "0 16px", borderBottom: "1px solid var(--border)", gap: 8, flexShrink: 0 }}>
        <button className="ibtn ibtn-sm" onClick={() => open("tab=coding")} aria-label="Back to sessions">
          <Ic n="arrow-left" s={15} />
        </button>
        <span className="mono faint" style={{ fontSize: 12 }}>
          {t.key}
        </span>
        <b className="trunc" style={{ fontWeight: 600, fontSize: 13.5 }}>
          {t.title}
        </b>
        <span className={`badge ${c}`}>{label}</span>
        <span className="sp" />
        <button className="btn btn-sm btn-ghost" onClick={() => openTask(t.id)}>
          <Ic n="panel-right-open" s={14} />
          Open task
        </button>
      </div>
      <div className="chat-scroll">
        <div className="chat-col">
          <dl className="kv" style={{ marginBottom: 16 }}>
            <dt>
              <Ic n="bot" s={14} />
              Tool
            </dt>
            <dd>{toolName(cs.tool)}</dd>
            <dt>
              <Ic n="folder" s={14} />
              Project
            </dt>
            <dd>
              <span className="row" style={{ gap: 6 }}>
                <span className="pdot" style={css({ "--c": pColor(p) })} />
                {p.name}
              </span>
            </dd>
            <dt>
              <Ic n="git-branch" s={14} />
              Branch
            </dt>
            <dd className="mono" style={{ fontSize: 12 }}>
              {cs.branch ?? <span className="faint">made when it starts</span>}
            </dd>
            <dt>
              <Ic n="git-pull-request" s={14} />
              Pull request
            </dt>
            <dd>
              {cs.pr ? (
                <a href={cs.pr.url} target="_blank" rel="noreferrer" className="row" style={{ gap: 6, color: "var(--acc)" }}>
                  #{cs.pr.number}
                  <span className={`badge ${cs.pr.state === "merged" ? "accent" : cs.pr.state === "open" ? "green" : ""}`}>{cs.pr.state}</span>
                </a>
              ) : (
                <span className="faint">none yet</span>
              )}
            </dd>
          </dl>
          {cs.turns.map((turn, i) => (
            <div key={i} style={{ marginBottom: 14 }}>
              <div className="chat-msg user">
                <Av id={cs.by} cls="md" tip={false} />
                <div className="body">
                  <div className="who">
                    <b>{who(cs.by)?.name}</b>
                    <time>
                      Turn {i + 1} · {ago(turn.at)}
                    </time>
                  </div>
                  <div className="bubble">{turn.ask}</div>
                </div>
              </div>
              {(turn.events.length > 0 || turn.summary) && (
                <div className="chat-msg">
                  <Av id={`agent:${cs.tool}`} cls="md" tip={false} />
                  <div className="body">
                    <div className="who">
                      <b>{toolName(cs.tool)}</b>
                    </div>
                    <div className="chat-act" style={{ flexDirection: "column", gap: 2 }}>
                      {turn.events.map((e) => (
                        <span key={e}>
                          <Ic n="chevron-right" s={11} />
                          {e}
                        </span>
                      ))}
                    </div>
                    {turn.summary && <div className="md">{turn.summary}</div>}
                  </div>
                </div>
              )}
            </div>
          ))}
          {cs.status === "awaiting_approval" && (
            <div className="change">
              <div className="change-h">
                <Ic n="shield-check" s={14} />
                <b style={{ fontWeight: 500 }}>Waiting for someone who may approve agent changes</b>
              </div>
              <div className="change-f">
                <span className="faint" style={{ fontSize: 12 }}>
                  It works on its own branch and opens a pull request; a person merges.
                </span>
                <span className="sp" />
                <button className="btn btn-sm btn-secondary" onClick={() => decideCoding(cs, false)}>
                  Reject
                </button>
                <button className="btn btn-sm btn-primary" onClick={() => decideCoding(cs, true)}>
                  <Ic n="check" s={13} />
                  Approve
                </button>
              </div>
            </div>
          )}
          {cs.status === "running" && (
            <div className="row" style={{ gap: 8 }}>
              <span className="chat-typing">
                <i />
                <i />
                <i />
              </span>
              <span className="muted" style={{ fontSize: 12.5 }}>
                {toolName(cs.tool)} is working
              </span>
              <span className="sp" />
              <button className="btn btn-sm btn-secondary" onClick={() => stopCoding(cs)}>
                <Ic n="square" s={12} />
                Stop
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="chat-input">
        <div className="cbox">
          <textarea rows={2} placeholder={busy ? "A turn is waiting or working…" : `Ask ${toolName(cs.tool)} for a follow-up on the same branch`} value={ask} disabled={busy} onChange={(e) => setAsk(e.target.value)} aria-label="Follow-up" onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && (followUp(cs, ask), setAsk(""))} />
          <div className="row">
            <span className="faint" style={{ fontSize: 11.5 }}>
              {MOD}+Enter to send · approved like the first turn
            </span>
            <span className="sp" />
            <button
              className="btn btn-primary btn-sm"
              disabled={busy || !ask.trim()}
              onClick={() => {
                followUp(cs, ask);
                setAsk("");
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

/* ---------- the page ---------- */

export function Chat() {
  const { search } = useRoute();
  const coding = search.get("tab") === "coding";
  const th = D().threads.find((t) => t.id === search.get("thread")) ?? null;
  const cs = D().coding.find((c) => c.id === search.get("session")) ?? null;
  const projectKey = search.get("project");
  const across = search.get("across") === "1";
  const q = S.ui.chatQ.toLowerCase();
  const ps = visibleProjects().filter(canSee);
  const threads = D()
    .threads.filter((t) => (t.project ? canSee(proj(t.project)) : t.by === D().me))
    .filter((t) => !q || t.title.toLowerCase().includes(q))
    .sort((a, b) => b.at - a.at);
  const sessions = D()
    .coding.filter((c) => canSee(proj(c.project)))
    .filter((c) => !q || `${task(c.task)?.key} ${task(c.task)?.title}`.toLowerCase().includes(q))
    .sort((a, b) => b.at - a.at);
  const waitingCoding = D().coding.filter((c) => c.status === "awaiting_approval").length;
  const hasSel = Boolean(th || cs || projectKey || across || search.get("q") || search.get("new"));
  return (
    <div className="page flush">
      <div className={`chat-grid ${hasSel ? "has-sel" : ""}`}>
        <aside className="chat-side">
          <div style={{ padding: "18px 14px 8px" }} className="row">
            <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>Chat</h1>
            <span className="sp" />
            <button className="btn btn-sm btn-primary" onClick={() => open(coding ? "tab=coding" : "new=1")} disabled={coding}>
              <Ic n="plus" s={13} />
              New chat
            </button>
          </div>
          <div style={{ padding: "0 14px 8px" }}>
            <div className="seg" style={{ width: "100%" }}>
              <button className={!coding ? "on" : ""} style={{ flex: 1 }} onClick={() => open("")}>
                <Ic n="message-square" s={13} />
                Conversations
              </button>
              <button className={coding ? "on" : ""} style={{ flex: 1 }} onClick={() => open("tab=coding")}>
                <Ic n="code" s={13} />
                Coding
                {waitingCoding > 0 && <span className="badge amber" style={{ height: 16, padding: "0 5px" }}>{waitingCoding}</span>}
              </button>
            </div>
            <div className="inwrap" style={{ marginTop: 8 }}>
              <Ic n="search" s={13} />
              <input className="input search-sm" style={{ width: "100%" }} placeholder={coding ? "Find a session" : "Find a conversation"} value={S.ui.chatQ} onChange={(e) => ((S.ui.chatQ = e.target.value), render())} aria-label="Find" />
            </div>
          </div>
          <div className="chat-list">
            {coding ? (
              sessions.length ? (
                ps
                  .filter((p) => sessions.some((c) => c.project === p.id))
                  .map((p) => (
                    <div key={p.id} style={{ marginTop: 10 }}>
                      <div className="row" style={{ padding: "0 8px", height: 26, fontSize: 11.5, color: "var(--text-3)", fontWeight: 500 }}>
                        <span className="pdot" style={css({ "--c": pColor(p), width: 7, height: 7 })} />
                        {p.name}
                      </div>
                      {sessions
                        .filter((c) => c.project === p.id)
                        .map((c) => (
                          <SessionRow key={c.id} cs={c} on={cs?.id === c.id} />
                        ))}
                    </div>
                  ))
              ) : (
                <Empty icon="code" title="No coding sessions" text="Use “Start coding” on a task, or assign it to Claude Code or Codex." cls="sm" />
              )
            ) : (
              <>
                {ps.map((p) => {
                  const list = threads.filter((t) => t.project === p.id);
                  if (!list.length && q) return null;
                  return (
                    <Group key={p.id} title={p.name} color={pColor(p)} onNew={() => open(`project=${p.key}`)}>
                      {list.length ? list.map((t) => <ThreadRow key={t.id} th={t} on={th?.id === t.id} />) : <div className="faint" style={{ fontSize: 12, padding: "2px 8px 4px" }}>No conversations yet</div>}
                    </Group>
                  );
                })}
                <Group title="Across projects" icon={<Ic n="layers" s={12} />} onNew={() => open("across=1")}>
                  {threads
                    .filter((t) => !t.project)
                    .map((t) => (
                      <ThreadRow key={t.id} th={t} on={th?.id === t.id} />
                    ))}
                </Group>
              </>
            )}
          </div>
        </aside>
        <section className="chat-main">
          {coding ? (
            cs ? (
              <Session key={cs.id} cs={cs} />
            ) : (
              <div className="fullstate">
                <div className="box">
                  <Empty icon="code" title="Coding sessions" text="Each session is a coding tool working on a task: its turns, its branch, and its pull request. Pick one to follow it or ask for a follow-up." />
                </div>
              </div>
            )
          ) : th ? (
            <Conversation key={th.id} th={th} />
          ) : (
            <NewChat key={`${projectKey}-${across}-${search.get("q")}`} projectKey={projectKey} across={across} q={search.get("q") ?? ""} agent0={search.get("agent")} />
          )}
        </section>
      </div>
    </div>
  );
}
