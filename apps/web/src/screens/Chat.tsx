// dotrix's workspace Chat in Gr8r's design (Gr8r has none): conversations grouped by project (and
// "All projects"), a new chat with project, agent, and model; replies with what the agent did
// and the changes it proposes; and the Coding tab, coding sessions with their turns.
// URL: ?project=KEY&thread=ID, ?tab=coding&session=ID, ?q= (start with a question), ?agent=.
import { useEffect, useRef, useState, type CSSProperties } from "react";

import { continueLimited, decideCoding, followUp, newThread, sendChat, startCoding, stopCoding } from "../core/agents";
import { LimitNotice } from "../components/LimitNotice";
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
import { useAtPicker } from "../components/AtPicker";

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
        {m.limit && !m.limit.continued && (
          <LimitNotice provider={m.limit.provider} resetsAt={m.limit.resetsAt} whenReset={m.limit.whenReset} onContinue={(w) => continueLimited({ thread: th.id, project: th.project ?? undefined }, w)} />
        )}
      </div>
    </div>
  );
}

const MODELS_ICON = "cpu";

function Pick({ value, onChange, options, label, lead }: { value: string; onChange: (v: string) => void; options: [string, string][]; label: string; lead?: React.ReactNode }) {
  return (
    <label className="cpill pick">
      {lead}
      <span className="trunc">{options.find(([v]) => v === value)?.[1] ?? value}</span>
      <Ic n="chevron-down" s={11} />
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  );
}

function Composer({ placeholder, onSend, agent, setAgent, model, setModel, autoFocus, initial = "", context, contexts, setContext }: { placeholder: string; onSend: (text: string, agent: string) => void; agent: string; setAgent: (a: string) => void; model?: string; setModel?: (m: string) => void; autoFocus?: boolean; initial?: string; context?: string; contexts?: [string, string][]; setContext?: (v: string) => void }) {
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  const a = D().agents.find((x) => x.handle === agent);
  // Typing "@" offers the projects (in a new chat) and the agents.
  const at = useAtPicker({ text, setText, ref, projects: contexts, project: context, onProject: setContext, agent, onAgent: setAgent });
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
    <div style={{ position: "relative" }}>
    <div className="cbox">
      <textarea
        ref={ref}
        rows={2}
        placeholder={placeholder}
        value={text}
        onChange={(e) => at.onChange(e.target)}
        onKeyDown={(e) => {
          if (at.onKeyDown(e)) return;
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        aria-label="Message"
        aria-expanded={at.open}
      />
      <div className="cbox-row">
        {contexts && setContext && context !== undefined ? (
          <button className="cpill pick" onClick={at.start} aria-label={`Project: ${contexts.find(([v]) => v === context)?.[1]}. Type @ to change it`} data-tip="Type @ to pick another project">
            <Ic n={context ? "at-sign" : "layers"} s={12} />
            <span className="trunc">{contexts.find(([v]) => v === context)?.[1]}</span>
          </button>
        ) : (
          context && (
            <span className="cpill" data-tip="What the agents read: the project's documents and board">
              <Ic n="at-sign" s={12} />
              {context}
            </span>
          )
        )}
        <Pick value={agent} onChange={setAgent} options={D().agents.map((x) => [x.handle, `${x.name} · ${x.role}`])} label="Agent" lead={a && <Face c={a.c} size={16} mood="idle" />} />
        {setModel ? (
          <Pick value={model ?? MODELS[0]!} onChange={setModel} options={MODELS.map((x) => [x, x])} label="Model" lead={<Ic n={MODELS_ICON} s={12} />} />
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
    {at.menu}
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
            {(th.projects ?? []).map((id) => proj(id)?.name).join(", ") || "All projects"}
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
        <Composer placeholder={`Ask ${agentName(agent)}, or type @ to pick an agent`} agent={agent} setAgent={setAgent} model={th.model} context={p?.name ?? "All projects"} onSend={(q, a) => sendChat(th, q, a)} autoFocus />
        {!th.project && (
          <div className="faint" style={{ fontSize: 11.5, marginTop: 6 }}>
            <Ic n="lock" s={11} /> In all projects the agents only read; for a change they'll say which project's chat to ask in.
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
    <div className="chat-scroll" style={{ display: "flex" }}>
      <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
        <h1 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>
          {greeting()}, {me()?.name.split(" ")[0]}
        </h1>
        <p className="muted" style={{ margin: "0 0 18px", textAlign: "center" }}>
          Ask the agents about a project: they read its documents and board, and propose changes for you to approve.
        </p>
        {!pid && (
        <div className="row" style={{ gap: 6, marginBottom: 10, flexWrap: "wrap", justifyContent: "center" }}>
          <span className="faint" style={{ fontSize: 12 }}>
            Projects
          </span>
          {ps.map((p) => (
              <label key={p.id} className="badge" style={{ cursor: "pointer", gap: 5 }}>
                <input type="checkbox" checked={picked.includes(p.id)} onChange={() => setPicked(picked.includes(p.id) ? picked.filter((x) => x !== p.id) : [...picked, p.id])} />
                {p.name}
              </label>
            ))}
        </div>
        )}
        <Composer
          key={q}
          placeholder="Ask anything, or type @ to pick a project or an agent"
          agent={agent}
          setAgent={setAgent}
          model={model}
          setModel={setModel}
          context={pid}
          contexts={[...ps.map((p): [string, string] => [p.id, p.name]), ["", "All projects"]]}
          setContext={setPid}
          onSend={start}
          autoFocus
          initial={q}
        />
        <div className="row" style={{ gap: 6, flexWrap: "wrap", marginTop: 14, justifyContent: "center" }}>
          {sugg.map(([i, s]) => (
            <button key={s} className="btn btn-secondary btn-sm" onClick={() => start(s!, agent)} disabled={!pid && !picked.length}>
              <Ic n={i!} s={13} />
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- a new coding session ---------- */

const TOOLS: ["claude-code" | "codex", string][] = [
  ["claude-code", "Claude Code"],
  ["codex", "Codex"],
];

function NewSession({ issue0 }: { issue0: string | null }) {
  // Issues a tool could work on: open ones in the projects you see, and in an organisation only yours.
  const ps = new Set(visibleProjects().filter((p) => canSee(p) && !p.archived).map((p) => p.id));
  const personal = D().ws.kind === "personal";
  const mine = D().tasks.filter((t) => ps.has(t.project) && !t.archived && t.status !== "done" && t.type !== "epic" && (personal || t.assignee === D().me));
  const [tid, setTid] = useState(issue0 ? (D().tasks.find((t) => t.key === issue0)?.id ?? "") : "");
  const [tool, setTool] = useState<"claude-code" | "codex">("claude-code");
  const [note, setNote] = useState("");
  const [menu, setMenu] = useState<string | null>(null);
  const [hl, setHl] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const t = task(tid);
  const found =
    menu === null
      ? []
      : mine.filter((x) => `${x.key} ${x.title}`.toLowerCase().includes(menu.toLowerCase())).slice(0, 8);
  const go_ = () => {
    if (!t) return;
    const id = startCoding(t, tool, note);
    if (id) open(`tab=coding&session=${id}`);
  };
  const onText = (el: HTMLTextAreaElement) => {
    setNote(el.value);
    const m = el.value.slice(0, el.selectionStart).match(/(?:^|\s)[@/]([\w-]*)$/);
    setMenu(m ? m[1]! : null);
    setHl(0);
  };
  const pick = (id: string) => {
    setTid(id);
    setNote(note.replace(/(^|\s)[@/][\w-]*$/, "$1").replace(/\s+$/, ""));
    setMenu(null);
    ref.current?.focus();
  };
  const ask = () => {
    setNote(note + (note && !note.endsWith(" ") ? " @" : "@"));
    setMenu("");
    setHl(0);
    ref.current?.focus();
  };
  return (
    <div className="chat-scroll" style={{ display: "flex" }}>
      <div className="chat-col" style={{ margin: "auto", paddingTop: 56, paddingBottom: 40 }}>
        <h1 style={{ fontSize: "var(--fs-2xl)", fontWeight: 600, letterSpacing: "-.02em", margin: "0 0 4px", textAlign: "center" }}>Start a coding session</h1>
        <p className="muted" style={{ margin: "0 0 18px", textAlign: "center" }}>
          A coding tool works on an issue on its own branch and opens a pull request. It starts once someone who may approve agent changes says yes.
        </p>
        <div style={{ position: "relative" }}>
        <div className="cbox">
          <textarea
            ref={ref}
            rows={3}
            value={note}
            autoFocus
            placeholder={t ? `What should it do? It gets ${t.key}'s description and acceptance criteria either way` : `Type @ or / to pick ${personal ? "an issue" : "one of your issues"}, then say what to do`}
            onChange={(e) => onText(e.target)}
            onKeyDown={(e) => {
              if (menu !== null && found.length) {
                if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                  e.preventDefault();
                  setHl((hl + (e.key === "ArrowDown" ? 1 : found.length - 1)) % found.length);
                  return;
                }
                if ((e.key === "Enter" && !e.metaKey && !e.ctrlKey) || e.key === "Tab") {
                  e.preventDefault();
                  pick(found[hl]!.id);
                  return;
                }
              }
              if (e.key === "Escape" && menu !== null) {
                e.stopPropagation();
                setMenu(null);
              }
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go_();
            }}
            aria-label="What should it do"
            aria-expanded={menu !== null}
            aria-controls="cs-issues"
          />
          <div className="cbox-row">
            {t ? (
              <span className="cpill" style={{ color: "var(--text)" }}>
                <Ic n="square-check" s={12} />
                <span className="trunc">
                  {t.key} {t.title}
                </span>
                <button className="ibtn ibtn-xs" style={{ width: 16, height: 16, marginRight: -4 }} onClick={() => setTid("")} aria-label={`Remove ${t.key}`}>
                  <Ic n="x" s={11} />
                </button>
              </span>
            ) : (
              <button className="cpill pick" onClick={ask} aria-label="Pick an issue">
                <Ic n="at-sign" s={12} />
                Issue
              </button>
            )}
            <div className="seg" role="radiogroup" aria-label="Tool">
              {TOOLS.map(([id, name]) => (
                <button key={id} role="radio" aria-checked={tool === id} className={tool === id ? "on" : ""} onClick={() => setTool(id)}>
                  <Face c={who(`agent:${id}`)?.c ?? "var(--acc)"} size={14} />
                  {name}
                </button>
              ))}
            </div>
            <span className="sp" />
            <span className="faint hide-m" style={{ fontSize: 11 }}>
              {MOD}+Enter to start
            </span>
            <button className="btn btn-sm btn-primary" onClick={go_} disabled={!t}>
              <Ic n="code" s={13} />
              Start coding
            </button>
          </div>
        </div>
        {menu !== null && (
          <div className="pop" id="cs-issues" role="listbox" aria-label="Issues" style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, maxWidth: 520 }}>
            {found.length ? (
              found.map((x, i) => (
                <button key={x.id} role="option" aria-selected={i === hl} className={`mi ${i === hl ? "hl" : ""}`} onMouseEnter={() => setHl(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(x.id)}>
                  <span className="faint" style={{ fontSize: 12, width: 64, flexShrink: 0 }}>
                    {x.key}
                  </span>
                  <span className="trunc" style={{ flex: 1 }}>
                    {x.title}
                  </span>
                  <span className="r">{proj(x.project)?.name}</span>
                </button>
              ))
            ) : (
              <div className="faint" style={{ padding: "8px 10px", fontSize: 12.5 }}>
                {mine.length ? "No issue matches." : personal ? "No open issues." : "No open issues are assigned to you."}
              </div>
            )}
          </div>
        )}
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
  // Its details (tool, project, branch, PR) wait behind "⋯", unless you came from its issue or it just started.
  const fromIssue = new URLSearchParams(location.search).get("from") === "issue";
  const justStarted = cs.turns.length === 1 && Date.now() - cs.at < 2 * 60_000;
  const [info, setInfo] = useState(fromIssue || justStarted);
  useEffect(() => setInfo(fromIssue || justStarted), [cs.id]); // eslint-disable-line react-hooks/exhaustive-deps
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
        <button
          className={`ibtn ibtn-sm ${info ? "on" : ""}`}
          onClick={() => setInfo(!info)}
          aria-label={info ? "Hide the session's details" : "Show the session's details"}
          aria-expanded={info}
          data-tip="Details"
        >
          <Ic n="ellipsis-vertical" s={15} />
        </button>
        <span className="sp" />
        <button className="btn btn-sm btn-ghost" onClick={() => openTask(t.id)}>
          <Ic n="panel-right-open" s={14} />
          Open task
        </button>
      </div>
      <div className="chat-scroll">
        <div className="chat-col">
          {info && (
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
          )}
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
            <h1 style={{ fontSize: "var(--fs-xl)", margin: 0, fontWeight: 600, letterSpacing: "-.015em" }}>{coding ? "Code" : "Chat"}</h1>
            <span className="sp" />
            <div className="seg seg-icons" role="tablist" aria-label="Chat or code">
              <button role="tab" aria-selected={!coding} className={!coding ? "on" : ""} onClick={() => open("")} aria-label="Chat" data-tip="Chat">
                <Ic n="message-square" s={14} />
              </button>
              <button
                role="tab"
                aria-selected={coding}
                className={coding ? "on" : ""}
                onClick={() => open("tab=coding")}
                aria-label={waitingCoding ? `Code, ${waitingCoding} waiting for approval` : "Code"}
                data-tip="Code"
              >
                <Ic n="code" s={14} />
                {waitingCoding > 0 && <span className="badge amber seg-n">{waitingCoding}</span>}
              </button>
            </div>
          </div>
          <div style={{ padding: "0 14px 8px" }}>
            <div className="inwrap">
              <Ic n="search" s={13} />
              <input className="input search-sm" style={{ width: "100%" }} placeholder={coding ? "Find a session" : "Find a conversation"} value={S.ui.chatQ} onChange={(e) => ((S.ui.chatQ = e.target.value), render())} aria-label="Find" />
            </div>
            {/* Start something new, under the search: a conversation, or a coding session on the Code tab. */}
            <button className={`sitem chat-new ${(coding ? !cs : !th && !projectKey && !across) ? "on" : ""}`} onClick={() => open(coding ? "tab=coding" : "new=1")}>
              <Ic n={coding ? "code" : "square-pen"} s={15} />
              <span className="trunc">{coding ? "New session" : "New chat"}</span>
            </button>
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
                <Group title="Conversations" icon={<Ic n="layers" s={12} />} onNew={() => open("across=1")}>
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
              <NewSession key={search.get("issue") ?? ""} issue0={search.get("issue")} />
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
