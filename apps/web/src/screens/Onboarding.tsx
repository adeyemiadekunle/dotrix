// Gr8r's onboarding (gr8r-studio/src/pages/auth.js renderOnboarding): six steps in the auth
// shell. On the seeded data it renames the workspace, creates the first project from a template
// (dotrix: with its documents for the agents), and adds the invites. Wired later to
// POST /v1/workspaces, /projects, /invites.
import { useState } from "react";

import { Ic } from "../core/icons";
import { TEMPLATES, createProject } from "../core/more";
import { go } from "../core/nav";
import { uid } from "../core/utils";
import { D, me, mutate } from "../data/store";

type Data = { use: string; ws: string; url: string; team: string; size: string; proj: string; tmpl: string; invites: string[] };
const N = 6;

export function Onboarding() {
  const [st, setSt] = useState(0);
  const [o, setO] = useState<Data>({ use: "product", ws: "", url: "", team: "kanban", size: "2-10", proj: "My first project", tmpl: "product", invites: ["", "", ""] });
  const [err, setErr] = useState("");
  const set = (p: Partial<Data>) => setO({ ...o, ...p });
  const next = (skip = false) => {
    if (st === 1 && !o.ws.trim()) return setErr("Give your workspace a name");
    setErr("");
    if (st === 4 && skip) set({ invites: ["", "", ""] });
    setSt(st + 1);
  };
  const finish = () => {
    mutate(() => {
      D().ws.name = o.ws.trim() || "My Workspace";
      D().ws.url = o.url || "workspace";
      const tm = TEMPLATES.find((t) => t.id === o.tmpl);
      const p = createProject({ name: o.proj || "My first project", icon: tm?.icon || "folder", color: "indigo", team: me()!.team, lead: D().me }, o.tmpl);
      D().knowledge.push({ path: "project.md", project: p.id, content: `# ${p.name}\n\nWhat this project is for, who it serves, and what done looks like.\n`, version: 1, by: D().me, at: Date.now() });
      for (const email of o.invites.filter((x) => x.includes("@")))
        D().members.push({ id: uid("m"), name: email.split("@")[0]!, email, role: "Member", team: me()!.team, title: "", c: "#8A867E", status: "invited", last: null, tz: "" });
    });
    go("home");
  };
  const Opt = ({ k, v, icon, n, s }: { k: "use" | "team" | "tmpl"; v: string; icon: string; n: string; s?: string }) => (
    <button className={`opt ${o[k] === v ? "on" : ""}`} role="radio" aria-checked={o[k] === v} onClick={() => set({ [k]: v })}>
      <Ic n={icon} s={18} />
      <b>{n}</b>
      {s && <span>{s}</span>}
    </button>
  );
  const Nav = ({ label = "Continue", skip = false }: { label?: string; skip?: boolean }) => (
    <div className="row" style={{ marginTop: 6 }}>
      {st > 0 && st < 5 && (
        <button className="btn btn-ghost" onClick={() => setSt(st - 1)}>
          <Ic n="arrow-left" s={14} />
          Back
        </button>
      )}
      <span className="sp" />
      {skip && (
        <button className="btn btn-ghost" onClick={() => next(true)}>
          Skip for now
        </button>
      )}
      <button className="btn btn-primary btn-lg" onClick={() => next()} id="onb-next">
        {label}
        <Ic n="arrow-right" s={15} />
      </button>
    </div>
  );
  let body;
  if (st === 0)
    body = (
      <>
        <h1>What are you working on?</h1>
        <p className="sub">We&apos;ll tailor templates, views, and the agents&apos; suggestions. You can change this later.</p>
        <div className="opts" role="radiogroup">
          {[
            ["product", "target", "Product", "Roadmaps & launches"],
            ["design", "palette", "Design", "Reviews & handoff"],
            ["marketing", "megaphone", "Marketing", "Campaigns & content"],
            ["engineering", "code", "Engineering", "Sprints & releases"],
            ["personal", "user", "Personal", "Goals & side projects"],
            ["other", "sparkles", "Other", "Something else"],
          ].map(([v, i, n, s]) => (
            <Opt key={v} k="use" v={v!} icon={i!} n={n!} s={s} />
          ))}
        </div>
        <Nav />
      </>
    );
  if (st === 1)
    body = (
      <>
        <h1>Create your workspace</h1>
        <p className="sub">A workspace is where your team&apos;s projects, documents, and agents live.</p>
        <div className="field">
          <label className="label" htmlFor="o-ws">
            Workspace name
          </label>
          <input className={`input input-lg ${err ? "is-error" : ""}`} id="o-ws" value={o.ws} onChange={(e) => set({ ws: e.target.value, url: e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "") })} placeholder="e.g. Acme Studio" autoFocus />
          {err && (
            <span className="err">
              <Ic n="circle-alert" s={12} />
              {err}
            </span>
          )}
        </div>
        <div className="field">
          <label className="label" htmlFor="o-url">
            Workspace URL
          </label>
          <div className="row" style={{ gap: 0 }}>
            <span className="input input-lg" style={{ width: "auto", background: "var(--surface-2)", borderRight: 0, borderRadius: "6px 0 0 6px", display: "flex", alignItems: "center", color: "var(--text-2)" }}>
              dotrix.app/w/
            </span>
            <input className="input input-lg" id="o-url" value={o.url} onChange={(e) => set({ url: e.target.value })} style={{ borderRadius: "0 6px 6px 0" }} placeholder="acme" />
          </div>
          {o.url && (
            <span className="hint" style={{ color: "var(--green)", display: "flex", gap: 4, alignItems: "center" }}>
              <Ic n="check" s={12} />
              dotrix.app/w/{o.url} is available
            </span>
          )}
        </div>
        <Nav />
      </>
    );
  if (st === 2)
    body = (
      <>
        <h1>How does your team work?</h1>
        <p className="sub">We&apos;ll set your default project view.</p>
        <div className="opts" role="radiogroup" style={{ gridTemplateColumns: "repeat(2,minmax(0,1fr))" }}>
          {[
            ["kanban", "square-kanban", "Boards", "Move cards through stages"],
            ["list", "list-checks", "Lists", "Checklists and priorities"],
            ["timeline", "chart-gantt", "Timelines", "Plan with dates & dependencies"],
            ["table", "table-2", "Tables", "Spreadsheet-style tracking"],
          ].map(([v, i, n, s]) => (
            <Opt key={v} k="team" v={v!} icon={i!} n={n!} s={s} />
          ))}
        </div>
        <div className="field">
          <span className="label">Team size</span>
          <div className="seg" style={{ width: "fit-content" }}>
            {["Just me", "2-10", "11-50", "51-200", "200+"].map((s) => (
              <button key={s} className={o.size === s ? "on" : ""} onClick={() => set({ size: s })}>
                {s}
              </button>
            ))}
          </div>
        </div>
        <Nav />
      </>
    );
  if (st === 3)
    body = (
      <>
        <h1>Create your first project</h1>
        <p className="sub">Start from a template. The agents get a project.md to build on; add documents or a repo later.</p>
        <div className="field">
          <label className="label" htmlFor="o-proj">
            Project name
          </label>
          <input className="input input-lg" id="o-proj" value={o.proj} onChange={(e) => set({ proj: e.target.value })} autoFocus />
        </div>
        <div className="tmpls" role="radiogroup">
          {TEMPLATES.filter((t) => t.id !== "blank").map((t) => (
            <Opt key={t.id} k="tmpl" v={t.id} icon={t.icon} n={t.name} s={`${t.tasks.length} starter tasks`} />
          ))}
        </div>
        <Nav />
      </>
    );
  if (st === 4)
    body = (
      <>
        <h1>Invite your team</h1>
        <p className="sub">dotrix works best with your teammates. They&apos;ll get an email invite.</p>
        <div className="col" style={{ gap: 8 }}>
          {[0, 1, 2].map((i) => (
            <input
              key={i}
              className="input input-lg"
              placeholder="teammate@company.com"
              type="email"
              value={o.invites[i]}
              onChange={(e) => set({ invites: o.invites.map((x, j) => (j === i ? e.target.value : x)) })}
              aria-label={`Teammate email ${i + 1}`}
            />
          ))}
        </div>
        <Nav label="Send invites" skip />
      </>
    );
  if (st === 5) {
    const n = o.invites.filter((x) => x.includes("@")).length;
    const tm = TEMPLATES.find((t) => t.id === o.tmpl);
    body = (
      <>
        <div style={{ display: "flex", justifyContent: "center" }}>
          <span className="ftype ready-badge" style={{ "--c": "var(--green)", width: 48, height: 48, borderRadius: 12 } as React.CSSProperties}>
            <Ic n="circle-check" s={22} />
          </span>
        </div>
        <h1>Your workspace is ready</h1>
        <p className="sub">Here&apos;s what we set up for you.</p>
        <div className="panel">
          {[
            ["building-2", `Workspace “${o.ws || "My Workspace"}”`, "dotrix.app/w/" + (o.url || "workspace")],
            [tm?.icon || "folder", `Project “${o.proj}”`, `${tm?.tasks.length || 0} starter tasks · ${{ kanban: "Board", list: "List", timeline: "Timeline", table: "Table" }[o.team]} view`],
            ["sparkles", "Six agents, ready in Chat", "They read your documents and propose changes for you to approve"],
            ["user-plus", n ? `${n} invite${n > 1 ? "s" : ""} sent` : "No invites yet", n ? "They'll appear in Members once they join" : "Invite people any time from the sidebar"],
          ].map(([i, t, s]) => (
            <div key={t} className="row ready-row" style={{ padding: "12px 14px", borderTop: "1px solid var(--divider)", gap: 12 }}>
              <span className="ftype" style={{ "--c": "var(--acc)" } as React.CSSProperties}>
                <Ic n={i!} s={14} />
              </span>
              <div className="grow">
                <div style={{ fontWeight: 500 }}>{t}</div>
                <div className="faint" style={{ fontSize: 12 }}>
                  {s}
                </div>
              </div>
              <span className="ok" style={{ color: "var(--green)", display: "inline-flex" }}>
                <Ic n="check" s={15} />
              </span>
            </div>
          ))}
        </div>
        <button className="btn btn-primary btn-lg btn-block" onClick={finish}>
          Open workspace
          <Ic n="arrow-right" s={15} />
        </button>
      </>
    );
  }
  return (
    <div className="auth-card onb" style={{ maxWidth: st === 5 ? 440 : 560 }}>
      <div className="steps" aria-label={`Step ${st + 1} of ${N}`}>
        {Array.from({ length: N }, (_, i) => (
          <i key={i} className={`${i <= st ? "on" : ""} ${i === st ? "cur" : ""}`} />
        ))}
      </div>
      <div className="faint" style={{ textAlign: "center", fontSize: 12 }}>
        Step {st + 1} of {N}
      </div>
      {body}
      {st < 5 && (
        <button className="btn btn-ghost btn-sm" style={{ alignSelf: "center" }} onClick={() => go("home")}>
          Exit setup
        </button>
      )}
    </div>
  );
}
