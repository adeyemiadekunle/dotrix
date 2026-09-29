"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Checkbox } from "@pmagent/ui/components/checkbox";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@pmagent/ui/components/select";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { Textarea } from "@pmagent/ui/components/textarea";
import { HistoryIcon, PlusIcon, RotateCcwIcon, Trash2Icon, XIcon } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useConfirm } from "@/components/confirm-dialog";
import { Field, SaveBar } from "@/components/form";
import { timeAgo } from "@/components/issues/issue-activity";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { NotFound } from "@/components/states";
import { modelName, useModels } from "@/lib/agent";
import {
  ACCESS_LABELS,
  ACTION_LABELS,
  PM_HANDLE,
  SOURCE_LABELS,
  displayName,
  useAgentCatalog,
  useAgentVersions,
  useAgents,
  useDeleteAgent,
  useRestoreAgentVersion,
  useSaveAgent,
  type Access,
  type AgentDef,
  type AgentFields,
  type AgentScope,
} from "@/lib/agents";

type Rule = "allow" | "ask" | "block";
/** The form's state: every field present (the API fills in defaults for missing ones). */
type Form = Required<AgentFields>;
const HANDLE = /^[a-z][a-z0-9-]{1,30}$/;

const BLANK: Form = {
  name: "",
  description: "",
  instructions: "",
  model: null,
  budget_tokens: null,
  tools: ["knowledge.read", "knowledge.search", "board.read"],
  access: {},
  issue_types: [],
  can_call: [],
  autonomy: {},
  output: null,
  pipeline: null,
  triggers: [],
};

function fieldsOf(agent: AgentDef): Form {
  const { handle: _h, base: _b, source: _s, scope: _sc, version: _v, updated_at: _u, ...fields } = agent;
  return { ...BLANK, ...(fields as Partial<Form>) };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * One agent's contract: who it is, its instructions, model and budget, tools, the folders it may
 * change, the issues it may open, who it may call, and what it may do without asking. Owners and
 * admins edit it (only owners allow actions without asking); everyone else reads it.
 */
export function AgentEditor({
  scope,
  handle,
  base,
  canEdit,
  isOwner,
}: {
  scope: AgentScope;
  /** The agent's handle, or "new". */
  handle: string;
  /** The list page, e.g. /w/acme/agents. */
  base: string;
  canEdit: boolean;
  isOwner: boolean;
}) {
  const creating = handle === "new";
  const agents = useAgents(scope);
  const agent = creating ? undefined : agents.data?.find((a) => a.handle === handle);
  if (agents.isLoading) return <Skeleton className="h-96" />;
  if (!creating && !agent) return <NotFound what="agent" />;
  return (
    <Editor
      key={`${handle}-${agent?.version ?? "default"}-${agent?.scope ?? ""}`}
      scope={scope}
      agent={agent}
      others={(agents.data ?? []).filter((a) => a.handle !== handle && a.handle !== PM_HANDLE)}
      base={base}
      canEdit={canEdit}
      isOwner={isOwner}
    />
  );
}

function Editor({
  scope,
  agent,
  others,
  base,
  canEdit,
  isOwner,
}: {
  scope: AgentScope;
  agent: AgentDef | undefined;
  others: AgentDef[];
  base: string;
  canEdit: boolean;
  isOwner: boolean;
}) {
  const router = useRouter();
  const catalog = useAgentCatalog(scope.workspaceId);
  const models = useModels(scope.workspaceId);
  const save = useSaveAgent(scope);
  const remove = useDeleteAgent(scope);
  const [ask, confirmDialog] = useConfirm();
  const initial = agent ? fieldsOf(agent) : BLANK;
  const [fields, setFields] = useState<Form>(initial);
  const [handle, setHandle] = useState(agent?.handle ?? "");
  const [note, setNote] = useState("");
  const [newPattern, setNewPattern] = useState("");
  const isPm = agent?.handle === PM_HANDLE;
  const scopeName = scope.projectId ? "project" : "workspace";
  // Saving here edits this scope's definition; an agent shown from a wider scope starts a new one.
  const ownsDefinition = Boolean(agent && agent.version !== null && agent.scope === scopeName);
  const dirty = !same(fields, initial) || (!agent && handle !== "");
  const set = <K extends keyof Form>(key: K, value: Form[K]) => setFields((f) => ({ ...f, [key]: value }));
  const has = (tool: string) => fields.tools.includes(tool);
  const cat = catalog.data;

  function toggleTool(id: string, on: boolean) {
    const tools = on ? [...fields.tools, id] : fields.tools.filter((t) => t !== id);
    setFields((f) => ({
      ...f,
      tools,
      issue_types: tools.includes("issues.create") ? f.issue_types : [],
    }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const target = agent?.handle ?? handle.trim();
    const saved = await save
      .mutateAsync({
        handle: target,
        body: { agent: fields, note: note.trim(), base_version: ownsDefinition ? agent!.version : null },
      })
      .catch(() => null);
    if (saved && !agent) router.replace(`${base}/${saved.handle}`);
    if (saved) setNote("");
  }

  const actions = (cat?.tools ?? []).filter((t) => has(t.id)).flatMap((t) => t.actions);
  const title = agent ? displayName(agent) : "New agent";

  return (
    <form className="grid max-w-5xl content-start gap-8" onSubmit={onSubmit}>
      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle className="flex flex-wrap items-center gap-2">
            {title}
            {agent && <Badge variant="outline">{SOURCE_LABELS[agent.source]}</Badge>}
          </SettingsTitle>
          <SettingsDescription>
            {agent
              ? agent.scope === "project"
                ? "This project's own version of the agent."
                : agent.source === "built_in"
                  ? "A built-in agent, as it comes. Changing it makes a customised version here; you can reset it later."
                  : `Defined for the ${agent.scope === "workspace" ? "workspace" : "project"}.`
              : "An agent for a specific purpose. It answers in the chat when picked, and the project manager can ask it for help."}
            {agent?.version != null && ` Version ${agent.version}.`}
          </SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-4">
          {!agent && (
            <Field
              label="Handle"
              value={handle}
              onChange={(e) => setHandle(e.target.value.toLowerCase())}
              placeholder="security"
              pattern={HANDLE.source}
              title="2-31 lower-case letters, digits, and dashes, starting with a letter"
              hint="How people pick it in the chat: @handle. It can't change later."
              required
              disabled={!canEdit}
            />
          )}
          <Field label="Name" value={fields.name} onChange={(e) => set("name", e.target.value)} required maxLength={60} disabled={!canEdit} />
          <Field
            label="Description"
            value={fields.description}
            onChange={(e) => set("description", e.target.value)}
            maxLength={200}
            hint="One line, shown in the chat's + menu."
            disabled={!canEdit}
          />
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Instructions</SettingsTitle>
          <SettingsDescription>
            Its role, in Markdown. The workspace&apos;s base rules and the project&apos;s{" "}
            <code className="font-mono">agent-rules/{agent?.handle ?? (handle || "handle")}.md</code> are added to it
            {isPm ? ", with how to delegate, the board, and Chat and Action Mode" : ""}.
          </SettingsDescription>
        </SettingsHeader>
        <SettingsContent>
          <Textarea
            aria-label="Instructions"
            value={fields.instructions}
            onChange={(e) => set("instructions", e.target.value)}
            rows={12}
            maxLength={20000}
            required
            disabled={!canEdit}
            className="font-mono text-sm"
          />
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Model and budget</SettingsTitle>
          <SettingsDescription>Leave them empty to use the conversation&apos;s model and the project&apos;s budget.</SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="agent-model">Model when it&apos;s asked for help</Label>
            <Select
              value={fields.model ?? "__default"}
              onValueChange={(v) => set("model", v === "__default" ? null : v)}
              disabled={!canEdit}
            >
              <SelectTrigger id="agent-model" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__default">The project&apos;s specialist model</SelectItem>
                {(models.data ?? []).map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    <span className="font-mono text-xs">{modelName(m.id)}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Field
            label="Token budget when it leads"
            type="number"
            min={10000}
            max={10000000}
            step={1000}
            value={fields.budget_tokens ?? ""}
            onChange={(e) => set("budget_tokens", e.target.value ? Number(e.target.value) : null)}
            placeholder="The project's budget"
            disabled={!canEdit}
          />
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Tools</SettingsTitle>
          <SettingsDescription>What it can use. Changes still wait for approval unless you allow them below.</SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-3 sm:grid-cols-2">
          {(cat?.tools ?? []).map((tool) => (
            <Label key={tool.id} className="flex items-start gap-3 font-normal">
              <Checkbox
                className="mt-0.5"
                checked={has(tool.id)}
                onCheckedChange={(on) => toggleTool(tool.id, on === true)}
                disabled={!canEdit}
                aria-label={tool.label}
              />
              <span className="grid gap-0.5">
                <span className="font-medium">{tool.label}</span>
                <span className="text-muted-foreground text-xs">{tool.description}</span>
              </span>
            </Label>
          ))}
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Folder access</SettingsTitle>
          <SettingsDescription>
            Which parts of <code className="font-mono">.pmagent/</code> it may change. Anything not listed is read-only.
            Propose means it drafts the change for the folder&apos;s owner; <code className="font-mono">agent-rules/</code> is
            always people only.
          </SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-2">
          {!has("knowledge.write") && (
            <p className="text-muted-foreground text-xs">Without “Write documents” it can at most propose changes.</p>
          )}
          {Object.entries(fields.access).map(([pattern, level]) => (
            <div key={pattern} className="flex items-center gap-2">
              <code className="bg-muted flex-1 truncate rounded-md px-2 py-1.5 font-mono text-xs">{pattern}</code>
              <Select
                value={level}
                onValueChange={(v) => set("access", { ...fields.access, [pattern]: v as Access })}
                disabled={!canEdit}
              >
                <SelectTrigger className="w-32" aria-label={`Access to ${pattern}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(cat?.access_levels ?? []).map((l) => (
                    <SelectItem key={l} value={l}>
                      {ACCESS_LABELS[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {canEdit && (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  aria-label={`Remove ${pattern}`}
                  onClick={() => {
                    const { [pattern]: _gone, ...rest } = fields.access;
                    set("access", rest);
                  }}
                >
                  <XIcon />
                </Button>
              )}
            </div>
          ))}
          {canEdit && (
            <div className="flex gap-2">
              <Input
                value={newPattern}
                onChange={(e) => setNewPattern(e.target.value)}
                placeholder="reviews/security/*"
                aria-label="Folder pattern"
                className="font-mono text-xs"
              />
              <Button
                type="button"
                variant="outline"
                disabled={!newPattern.trim() || newPattern.trim() in fields.access}
                onClick={() => {
                  set("access", { ...fields.access, [newPattern.trim()]: "write" });
                  setNewPattern("");
                }}
              >
                <PlusIcon />
                Add
              </Button>
            </div>
          )}
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>Issues and helpers</SettingsTitle>
          <SettingsDescription>The issue types it may open, and which agents it may ask for help when it leads a chat.</SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-5">
          <div className="grid gap-2">
            <p className="text-sm font-medium">Issue types it may open</p>
            {!has("issues.create") && <p className="text-muted-foreground text-xs">Needs the “Open issues” tool.</p>}
            <div className="flex flex-wrap gap-4">
              {(cat?.issue_types ?? []).map((type) => (
                <Label key={type} className="flex items-center gap-2 font-normal capitalize">
                  <Checkbox
                    checked={fields.issue_types.includes(type)}
                    disabled={!canEdit || !has("issues.create")}
                    onCheckedChange={(on) =>
                      set("issue_types", on === true ? [...fields.issue_types, type] : fields.issue_types.filter((t) => t !== type))
                    }
                  />
                  {type}
                </Label>
              ))}
            </div>
          </div>
          <div className="grid gap-2">
            <p className="text-sm font-medium">Agents it may ask</p>
            {!has("delegate") && <p className="text-muted-foreground text-xs">Needs the “Ask other agents” tool.</p>}
            <div className="flex flex-wrap gap-4">
              <Label className="flex items-center gap-2 font-normal">
                <Checkbox
                  checked={fields.can_call.includes("*")}
                  disabled={!canEdit || !has("delegate")}
                  onCheckedChange={(on) => set("can_call", on === true ? ["*"] : [])}
                />
                Every agent
              </Label>
              {others.map((other) => (
                <Label key={other.handle} className="flex items-center gap-2 font-normal">
                  <Checkbox
                    checked={fields.can_call.includes("*") || fields.can_call.includes(other.handle)}
                    disabled={!canEdit || !has("delegate") || fields.can_call.includes("*")}
                    onCheckedChange={(on) =>
                      set("can_call", on === true ? [...fields.can_call, other.handle] : fields.can_call.filter((h) => h !== other.handle))
                    }
                  />
                  {displayName(other)}
                </Label>
              ))}
            </div>
          </div>
        </SettingsContent>
      </SettingsSection>

      <SettingsSection>
        <SettingsHeader>
          <SettingsTitle>What it may do without asking</SettingsTitle>
          <SettingsDescription>
            Every change waits for a person&apos;s approval unless an owner allows it here, and only low-risk actions can be
            allowed. Block takes the action away entirely.
          </SettingsDescription>
        </SettingsHeader>
        <SettingsContent className="grid gap-2">
          {actions.length === 0 && <p className="text-muted-foreground text-sm">Its tools don&apos;t change anything.</p>}
          {actions.map((action) => {
            const lowRisk = cat?.low_risk_actions.includes(action) ?? false;
            const rule = (fields.autonomy[action] ?? "ask") as Rule;
            return (
              <div key={action} className="flex items-center justify-between gap-3">
                <span className="text-sm">{ACTION_LABELS[action] ?? action}</span>
                <Select
                  value={rule}
                  onValueChange={(v) => {
                    const { [action]: _old, ...rest } = fields.autonomy;
                    set("autonomy", v === "ask" ? rest : { ...rest, [action]: v as Rule });
                  }}
                  disabled={!canEdit}
                >
                  <SelectTrigger className="w-44" aria-label={`${ACTION_LABELS[action] ?? action}: without asking`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ask">Ask first</SelectItem>
                    <SelectItem value="allow" disabled={!lowRisk || !isOwner}>
                      Allow{!lowRisk ? " (not for this)" : !isOwner ? " (owners only)" : ""}
                    </SelectItem>
                    <SelectItem value="block">Block</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            );
          })}
        </SettingsContent>
      </SettingsSection>

      {canEdit && dirty && (
        <Field
          label="What changed (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={500}
          placeholder="Shown in its history"
        />
      )}
      {canEdit && (
        <SaveBar
          dirty={dirty}
          pending={save.isPending}
          onDiscard={() => {
            setFields(initial);
            setHandle(agent?.handle ?? "");
          }}
          label={agent ? "Save changes" : "Create agent"}
        />
      )}

      {agent && <History scope={scope} agent={agent} canEdit={canEdit} ownsDefinition={ownsDefinition} />}

      {agent && canEdit && ownsDefinition && (
        <SettingsSection>
          <SettingsHeader>
            <SettingsTitle>{agent.source === "custom" && agent.scope === scopeName ? "Remove" : "Reset"}</SettingsTitle>
            <SettingsDescription>
              {agent.scope === "project"
                ? "Drop this project's version; the workspace's applies again."
                : agent.source === "custom"
                  ? "Remove the agent from the workspace. Its history is kept."
                  : "Go back to the built-in agent. Its history is kept, so you can restore this version."}
            </SettingsDescription>
          </SettingsHeader>
          <SettingsContent>
            <Button
              type="button"
              variant="outline"
              onClick={() =>
                ask({
                  title: agent.source === "custom" && agent.scope === "workspace" ? `Remove @${agent.handle}?` : `Reset @${agent.handle}?`,
                  description: "Chats that pick it afterwards use what applies instead, or can't pick it if it's gone.",
                  confirm: agent.source === "custom" && agent.scope === "workspace" ? "Remove agent" : "Reset",
                  destructive: true,
                  action: async () => {
                    await remove.mutateAsync(agent.handle);
                    if (agent.source === "custom" && agent.scope === "workspace") router.replace(base);
                  },
                })
              }
            >
              {agent.source === "custom" && agent.scope === "workspace" ? <Trash2Icon /> : <RotateCcwIcon />}
              {agent.source === "custom" && agent.scope === "workspace" ? "Remove agent" : "Reset to default"}
            </Button>
          </SettingsContent>
        </SettingsSection>
      )}
      {confirmDialog}
    </form>
  );
}

function History({
  scope,
  agent,
  canEdit,
  ownsDefinition,
}: {
  scope: AgentScope;
  agent: AgentDef;
  canEdit: boolean;
  ownsDefinition: boolean;
}) {
  const [open, setOpen] = useState(false);
  const versions = useAgentVersions(scope, agent.handle, open);
  const restore = useRestoreAgentVersion(scope);
  return (
    <SettingsSection>
      <SettingsHeader>
        <SettingsTitle>History</SettingsTitle>
        <SettingsDescription>Every saved version, with who saved it and why.</SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="grid gap-2">
        {!open ? (
          <div>
            <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
              <HistoryIcon />
              Show history
            </Button>
          </div>
        ) : versions.isLoading ? (
          <Skeleton className="h-20" />
        ) : (versions.data ?? []).length === 0 || versions.isError ? (
          <p className="text-muted-foreground text-sm">No saved versions here yet.</p>
        ) : (
          <ul className="divide-y">
            {(versions.data ?? []).map((v) => (
              <li key={v.version} className="flex items-center gap-3 py-2 text-sm">
                <span className="font-mono text-xs">v{v.version}</span>
                <span className="min-w-0 flex-1 truncate">{v.note || <span className="text-muted-foreground">No note</span>}</span>
                <span className="text-muted-foreground text-xs">{timeAgo(v.created_at)}</span>
                {canEdit && (v.version !== agent.version || !ownsDefinition) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={restore.isPending}
                    onClick={() => restore.mutate({ handle: agent.handle, version: v.version })}
                  >
                    Restore
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SettingsContent>
    </SettingsSection>
  );
}
