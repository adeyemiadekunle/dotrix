// Dedicated workspace Skills Registry: category navigation, search, trust, provenance, and enablement.
import { useState } from "react";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { Textarea as DesignTextarea } from "@dotrix/ui/components/textarea";

import { allowed } from "../core/can";
import { Ic } from "../core/icons";
import { promptDlg } from "../core/more";
import { skillRegistry, skillSaved, useApi, type SkillRegistry, type SkillRegistryItem } from "../data/account";
import { isLive } from "../data/live";
import { Empty } from "../ui/helpers";
import { toast } from "../ui/toast";

export const AGENT_LABELS: Record<string, string> = {
  coding: "Kai",
  architecture: "Orion",
  product: "Lyra",
  reviewer: "Juno",
  research: "Vega",
  documentation: "Echo",
  "project-manager": "Nova",
};

export type TrustOriginFilter = "all" | "builtin" | "bundle" | "workspace";

export function agentDisplayName(handle: string): string {
  return AGENT_LABELS[handle] ?? handle;
}

export function filterSkills(items: SkillRegistryItem[], query: string, category: string, origin: TrustOriginFilter): SkillRegistryItem[] {
  const q = query.trim().toLowerCase();
  return items.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (origin !== "all" && item.origin !== origin) return false;
    if (!q) return true;
    const fields = [item.id, item.name, item.description, ...item.tags, ...item.agents, ...item.agents.map(agentDisplayName), ...(item.required_tools ?? [])];
    return fields.some((field) => field.toLowerCase().includes(q));
  });
}

const TRUST_BADGE: Record<string, { label: string; cls: string }> = {
  builtin: { label: "Built-in", cls: "badge gray" },
  reviewed: { label: "Reviewed", cls: "badge green" },
  workspace: { label: "Workspace", cls: "badge accent" },
};

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "try again");

function SkillRow({
  item,
  categoryLabel,
  canManage,
  open,
  onToggle,
  onSave,
}: {
  item: SkillRegistryItem;
  categoryLabel: string;
  canManage: boolean;
  open: boolean;
  onToggle: () => void;
  onSave: (id: string, content: string, baseVersion: number, notice: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(item.content);
  const [prevContent, setPrevContent] = useState(item.content);
  const [busy, setBusy] = useState(false);

  if (item.content !== prevContent) {
    setPrevContent(item.content);
    setDraft(item.content);
  }

  const trust = TRUST_BADGE[item.trust] ?? { label: item.trust, cls: "badge gray" };
  const editable = canManage && item.origin === "workspace";
  const changed = draft !== item.content;

  const runSave = async (nextContent: string, notice: string) => {
    setBusy(true);
    try {
      await onSave(item.id, nextContent, item.version, notice);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "flex-start" }}>
        <div className="grow" style={{ minWidth: 220 }}>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <Ic n="scroll-text" s={15} />
            <b style={{ fontWeight: 600 }}>{item.name}</b>
            <span className="mono faint" style={{ fontSize: 12 }}>
              {item.id}
            </span>
            <span className="badge gray">{categoryLabel}</span>
            <span className={trust.cls}>
              {item.trust === "reviewed" && <Ic n="shield-check" s={11} />}
              {trust.label}
            </span>
            <span className={`badge ${item.enabled ? "green" : "gray"}`}>
              <span className="dot" aria-hidden="true" />
              {item.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
          <p className="muted" style={{ fontSize: 13, margin: "6px 0 8px" }}>
            {item.description}
          </p>
          <div className="row faint" style={{ gap: 12, flexWrap: "wrap", fontSize: 12 }}>
            <span>Agents: {item.agents.length ? item.agents.map(agentDisplayName).join(", ") : "All agents"}</span>
            {item.required_tools.length > 0 && <span>Required tools: {item.required_tools.join(", ")}</span>}
            {item.tags.length > 0 && <span>Tags: {item.tags.join(", ")}</span>}
          </div>
          <div className="row faint" style={{ gap: 12, flexWrap: "wrap", fontSize: 11.5, marginTop: 4 }}>
            <span className="mono">
              sha256:{item.sha256.slice(0, 12)} · v{item.version || item.registry_version}
            </span>
            {item.source_repo && (
              <a className="row" style={{ gap: 3, color: "inherit", textDecoration: "underline" }} href={item.source_repo} target="_blank" rel="noreferrer">
                Source
                <Ic n="arrow-up-right" s={11} />
              </a>
            )}
            {item.source_revision && <span>Revision: {item.source_revision}</span>}
            {item.license && <span>License: {item.license}</span>}
          </div>
        </div>
        <div className="row" style={{ gap: 6, flexShrink: 0 }}>
          {canManage && item.origin === "bundle" && (
            <ActionButton
              className={item.enabled ? "btn btn-secondary btn-sm" : "btn btn-primary btn-sm"}
              disabled={busy}
              onClick={() => void runSave(item.enabled ? "" : item.content, item.enabled ? `${item.name} disabled` : `${item.name} enabled`)}
            >
              {item.enabled ? "Disable" : "Enable"}
            </ActionButton>
          )}
          <ActionButton className="btn btn-secondary btn-sm" onClick={onToggle} aria-expanded={open}>
            {open ? "Close" : editable ? "Edit" : "Inspect"}
          </ActionButton>
        </div>
      </div>
      {open && (
        <div style={{ marginTop: 12 }}>
          <DesignTextarea
            className="textarea mono"
            rows={12}
            value={editable ? draft : item.content}
            readOnly={!editable}
            onChange={(e) => setDraft(e.target.value)}
            style={{ fontSize: 12.5 }}
            aria-label={`${item.name} markdown`}
          />
          {editable ? (
            <div className="row" style={{ marginTop: 8, gap: 8 }}>
              <ActionButton className="btn btn-primary btn-sm" disabled={busy || !changed} onClick={() => void runSave(draft, `${item.name} saved`)}>
                Save
              </ActionButton>
              <span className="faint" style={{ fontSize: 12 }}>
                Save empty text to remove this workspace skill.
              </span>
            </div>
          ) : (
            <p className="faint" style={{ fontSize: 12, marginTop: 6 }}>
              {item.origin === "bundle"
                ? "Reviewed bundle pinned by SHA-256. Enable it to make its guidance available across this workspace."
                : "Built-in skill. Override per workspace or in a project's agent-rules/skills/ folder if needed."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export function SkillsCatalog({
  data,
  canManage,
  onSave,
}: {
  data: SkillRegistry;
  canManage: boolean;
  onSave: (id: string, content: string, baseVersion: number) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [origin, setOrigin] = useState<TrustOriginFilter>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const categoryLabels = new Map(data.categories.map((c) => [c.id, c.label]));
  const categoryCounts = new Map<string, number>();
  for (const item of data.items) {
    categoryCounts.set(item.category, (categoryCounts.get(item.category) ?? 0) + 1);
  }
  const filtered = filterSkills(data.items, query, category, origin);
  const enabledCount = data.items.filter((item) => item.enabled).length;

  const saveSkill = async (id: string, content: string, baseVersion: number, notice: string) => {
    try {
      await onSave(id, content, baseVersion);
      toast(notice);
    } catch (e: unknown) {
      toast(`Skill change failed: ${errText(e)}`, { kind: "err", ms: 6000 });
    }
  };

  return (
    <div className="page wide" style={{ maxWidth: 1020 }}>
      <div className="ph">
        <div>
          <h1>Skills</h1>
          <p>
            {enabledCount} enabled · {data.items.length} total across built-ins, reviewed bundles, and workspace skills. Skills provide procedures on demand
            without granting tool permissions.
          </p>
        </div>
        <div className="acts">
          {canManage && (
            <ActionButton
              className="btn btn-primary"
              onClick={() =>
                promptDlg({
                  title: "New workspace skill",
                  label: "Canonical ID (lowercase, with dashes)",
                  value: "",
                  run: (raw: string) => {
                    const id = raw
                      .trim()
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, "-")
                      .replace(/^-+|-+$/g, "");
                    if (!id) return;
                    const template = `Description: Describe when agents should read ${id}.\nCategory: general\nTags: workflow\n\n## Steps\n1. Inspect relevant context.\n2. Verify your result before finishing.\n`;
                    void saveSkill(id, template, 0, `Added ${id}`).then(() => setOpenId(id));
                  },
                })
              }
            >
              <Ic n="plus" s={14} />
              New skill
            </ActionButton>
          )}
        </div>
      </div>

      <div className="row" style={{ gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
        <div className="inwrap">
          <Ic n="search" s={13} />
          <input
            className="input search-sm"
            placeholder="Search skills, tags, or agents"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search skills"
          />
        </div>
        <div className="seg" role="tablist" aria-label="Skill trust and origin">
          {(
            [
              ["all", "All"],
              ["builtin", "Built-in"],
              ["bundle", "Reviewed bundles"],
              ["workspace", "Workspace"],
            ] as const
          ).map(([id, label]) => (
            <button key={id} className={origin === id ? "on" : ""} onClick={() => setOrigin(id)}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="row" style={{ gap: 6, marginBottom: 16, flexWrap: "wrap" }} role="tablist" aria-label="Skill categories">
        <button className={`btn btn-sm ${category === "all" ? "btn-primary" : "btn-secondary"}`} onClick={() => setCategory("all")}>
          All ({data.items.length})
        </button>
        {data.categories.map((cat) => (
          <button key={cat.id} className={`btn btn-sm ${category === cat.id ? "btn-primary" : "btn-secondary"}`} onClick={() => setCategory(cat.id)}>
            {cat.label} ({categoryCounts.get(cat.id) ?? 0})
          </button>
        ))}
      </div>

      {filtered.length ? (
        <div className="panel" style={{ overflow: "hidden" }}>
          {filtered.map((item) => (
            <SkillRow
              key={item.id}
              item={item}
              categoryLabel={categoryLabels.get(item.category) ?? item.category}
              canManage={canManage}
              open={openId === item.id}
              onToggle={() => setOpenId(openId === item.id ? null : item.id)}
              onSave={saveSkill}
            />
          ))}
        </div>
      ) : (
        <div className="panel">
          <Empty icon="search-x" title="No skills match" text="Try another search term, category, or origin filter.">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setQuery("");
                setCategory("all");
                setOrigin("all");
              }}
            >
              Clear filters
            </button>
          </Empty>
        </div>
      )}
    </div>
  );
}

const SAMPLE_REGISTRY: SkillRegistry = {
  categories: [
    { id: "frontend", label: "Frontend" },
    { id: "backend", label: "Backend" },
    { id: "architecture", label: "Architecture & System Design" },
    { id: "security", label: "Security" },
    { id: "testing", label: "Testing & QA" },
    { id: "browser", label: "Browser & Automation" },
    { id: "devops", label: "DevOps" },
    { id: "research", label: "Research & Data" },
    { id: "product", label: "Product & UX" },
    { id: "documentation", label: "Documentation" },
    { id: "general", label: "General" },
  ],
  items: [
    {
      id: "frontend-modern-web-guidance",
      name: "Modern Web Guidance",
      description: "Build accessible, resilient, high-performing web interfaces using modern web platform APIs.",
      category: "frontend",
      tags: ["web", "accessibility", "performance"],
      agents: ["coding", "architecture", "reviewer"],
      required_tools: [],
      trust: "reviewed",
      origin: "bundle",
      enabled: false,
      version: 0,
      registry_version: "1.0.0",
      sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      source_repo: "https://github.com/GoogleChrome/modern-web-guidance-src",
      source_revision: "curated-2026-11-22",
      license: "Apache-2.0",
      content: "# Skill: Modern Web Guidance\nDescription: Build accessible, resilient, high-performing web interfaces.\nCategory: frontend\n",
      updated_at: null,
    },
    {
      id: "browser-exploratory-verification",
      name: "Browser Exploratory Verification",
      description: "Inspect live local UIs with typed sandboxed browser operations and graduate key paths to Playwright.",
      category: "browser",
      tags: ["browser", "agent-browser", "playwright"],
      agents: ["coding", "reviewer"],
      required_tools: ["browser"],
      trust: "reviewed",
      origin: "bundle",
      enabled: true,
      version: 1,
      registry_version: "1.0.0",
      sha256: "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
      source_repo: "https://agent-browser.dev/introduction",
      source_revision: "curated-2026-11-22",
      license: "Apache-2.0",
      content: "# Skill: Browser Exploratory Verification\nRequires: browser\n",
      updated_at: null,
    },
    {
      id: "product-requirements-brief",
      name: "Product Requirements Brief",
      description: "Structure a product requirement brief with user problem, non-goals, and testable acceptance criteria.",
      category: "product",
      tags: ["prd", "requirements", "discovery"],
      agents: ["product", "project-manager"],
      required_tools: [],
      trust: "reviewed",
      origin: "bundle",
      enabled: false,
      version: 0,
      registry_version: "1.0.0",
      sha256: "2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
      source_repo: "https://github.com/anthropics/knowledge-work-plugins",
      source_revision: "curated-2026-11-22",
      license: "Apache-2.0",
      content: "# Skill: Product Requirements Brief\nCategory: product\n",
      updated_at: null,
    },
    {
      id: "write-an-adr",
      name: "Write an ADR",
      description: "Record an architecture decision so it can be followed and later superseded.",
      category: "architecture",
      tags: ["adr", "decisions", "design"],
      agents: ["architecture", "documentation", "project-manager"],
      required_tools: [],
      trust: "builtin",
      origin: "builtin",
      enabled: true,
      version: 0,
      registry_version: "1.0.0",
      sha256: "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
      source_repo: null,
      source_revision: "builtin",
      license: "Dotrix",
      content: "# Skill: write an ADR\nDescription: Record an architecture decision so it can be followed and later superseded.\n",
      updated_at: null,
    },
  ],
};

function LiveSkills() {
  const reg = useApi(skillRegistry);
  if (reg.error) return <div className="alert danger">{reg.error}</div>;
  if (!reg.data) return <div className="page wide faint">Loading skills registry…</div>;
  return (
    <SkillsCatalog
      data={reg.data}
      canManage={allowed("workspace:manage")}
      onSave={async (id, content, baseVersion) => {
        await skillSaved(id, content, baseVersion);
        reg.reload();
      }}
    />
  );
}

function SeedSkills() {
  const [data, setData] = useState<SkillRegistry>(SAMPLE_REGISTRY);
  return (
    <SkillsCatalog
      data={data}
      canManage={allowed("workspace:manage")}
      onSave={async (id, content, baseVersion) => {
        setData((prev) => {
          const next = prev.items.some((item) => item.id === id)
            ? prev.items.flatMap((item) => {
                if (item.id !== id) return [item];
                if (!content.trim() && item.origin === "workspace") return [];
                if (!content.trim() && item.origin === "bundle") return [{ ...item, enabled: false, version: baseVersion + 1 }];
                return [{ ...item, content, enabled: true, version: baseVersion + 1 }];
              })
            : [
                ...prev.items,
                {
                  id,
                  name: id.replaceAll("-", " "),
                  description: "Workspace skill",
                  category: "general",
                  tags: ["workflow"],
                  agents: [],
                  required_tools: [],
                  trust: "workspace",
                  origin: "workspace",
                  enabled: true,
                  version: baseVersion + 1,
                  registry_version: "1.0.0",
                  sha256: "0".repeat(64),
                  source_repo: null,
                  source_revision: null,
                  license: null,
                  content,
                  updated_at: null,
                },
              ];
          return { ...prev, items: next };
        });
      }}
    />
  );
}

export function Skills() {
  return isLive() ? <LiveSkills /> : <SeedSkills />;
}
