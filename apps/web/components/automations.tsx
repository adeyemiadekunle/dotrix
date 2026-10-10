import { Badge } from "@dotrix/ui/components/badge";
import { Button } from "@dotrix/ui/components/button";
import { Checkbox } from "@dotrix/ui/components/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@dotrix/ui/components/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@dotrix/ui/components/dropdown-menu";
import { Input } from "@dotrix/ui/components/input";
import { Label } from "@dotrix/ui/components/label";
import { Skeleton } from "@dotrix/ui/components/skeleton";
import { Textarea } from "@dotrix/ui/components/textarea";
import { PlayIcon, PlusIcon, ZapIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useConfirm } from "@/components/confirm-dialog";
import { FormError } from "@/components/form";
import { timeAgo } from "@/components/issues/issue-activity";
import {
  SettingsContent,
  SettingsDescription,
  SettingsHeader,
  SettingsSection,
  SettingsTitle,
} from "@/components/settings-section";
import { useChatAgents } from "@/lib/agents";
import { errorMessage } from "@/lib/api";
import {
  EVENT_LABELS,
  PRESETS,
  WEEKDAYS,
  describeWhen,
  useAutomations,
  useDeleteAutomation,
  useRunAutomation,
  useSaveAutomation,
  useToggleAutomation,
  type Automation,
  type AutomationCreate,
  type AutomationEvent,
} from "@/lib/automations";
import type { Scope } from "@/lib/issues";

/** Project settings → Automations: agents that run on a schedule or when something happens. */
export function Automations({
  scope,
  canEdit,
  workspaceSlug,
  projectKey,
}: {
  scope: Scope;
  canEdit: boolean;
  workspaceSlug: string;
  projectKey: string;
}) {
  const automations = useAutomations(scope);
  const toggle = useToggleAutomation(scope);
  const run = useRunAutomation(scope);
  const remove = useDeleteAutomation(scope);
  const agents = useChatAgents(scope);
  const [editing, setEditing] = useState<{ id?: string; body: AutomationCreate } | null>(null);
  const [ask, confirmDialog] = useConfirm();
  const agentName = (handle: string) => agents.find((a) => a.id === handle)?.name ?? `@${handle}`;
  const haveDocs = automations.data?.some((a) => a.events.includes("changes.approved"));

  return (
    <SettingsSection id="automations" stacked>
      <SettingsHeader>
        <SettingsTitle>Automations</SettingsTitle>
        <SettingsDescription>
          Agents that run on their own: on a schedule, or when people change issues or documents, approve agent
          changes, or push code (an agent&apos;s own changes never set them off). Each run is instructed by whoever set it
          up, and its changes wait for approval like anyone&apos;s.
        </SettingsDescription>
      </SettingsHeader>
      <SettingsContent className="p-0">
        {!automations.data ? (
          <Skeleton className="m-5 h-20" />
        ) : (
          <>
            {canEdit && !haveDocs && (
              <div className="bg-brand-muted/50 flex flex-wrap items-center gap-3 border-b p-4 text-sm">
                <ZapIcon className="text-primary size-4 shrink-0" />
                <p className="min-w-0 flex-1">
                  <span className="font-medium">Keep documents current:</span> after approved changes or finished issues,
                  the Documentation agent proposes the updates to the current state and roadmap.
                </p>
                <Button size="sm" variant="outline" onClick={() => setEditing({ body: PRESETS[0].body })}>
                  Set it up
                </Button>
              </div>
            )}
            {automations.data.length === 0 ? (
              <p className="text-muted-foreground p-5 text-sm">No automations yet.</p>
            ) : (
              <ul className="divide-y" aria-label="Automations">
                {automations.data.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-start gap-3 p-4">
                    {canEdit && (
                      <Checkbox
                        checked={a.enabled}
                        onCheckedChange={(c) => toggle.mutate({ id: a.id, enabled: c === true })}
                        aria-label={`${a.enabled ? "Turn off" : "Turn on"} ${a.name}`}
                        className="mt-0.5"
                      />
                    )}
                    <div className="grid min-w-0 flex-1 gap-0.5 text-sm">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {a.name}
                        <Badge variant="outline">{a.agent === "auto" ? "Auto" : agentName(a.agent)}</Badge>
                        {!a.enabled && <Badge variant="secondary">Off</Badge>}
                      </p>
                      <p className="text-muted-foreground text-xs">{describeWhen(a)}</p>
                      <p className="text-muted-foreground text-xs">
                        {a.last_run_at ? (
                          <>
                            Last ran {timeAgo(a.last_run_at)}
                            {a.thread_id && (
                              <>
                                {" · "}
                                <Link
                                  href={`/w/${workspaceSlug}/chat?project=${projectKey}&thread=${a.thread_id}`}
                                  className="underline underline-offset-4"
                                >
                                  open in Chat
                                </Link>
                              </>
                            )}
                          </>
                        ) : (
                          "Hasn't run yet"
                        )}
                        {` · ${a.runs_today} of ${a.max_runs_per_day} runs today`}
                      </p>
                      {a.last_error && <p className="text-destructive text-xs">{a.last_error}</p>}
                    </div>
                    {canEdit && (
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={run.isPending}
                          onClick={() => run.mutate(a.id)}
                          aria-label={`Run ${a.name} now`}
                        >
                          <PlayIcon />
                          Run now
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing({ id: a.id, body: toBody(a) })}>
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            ask({
                              title: `Delete ${a.name}?`,
                              description: "It stops running. Its past conversations stay in Chat.",
                              confirm: "Delete",
                              destructive: true,
                              action: () => remove.mutateAsync(a.id),
                            })
                          }
                        >
                          Delete
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {canEdit && (
              <div className="border-t p-4">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="outline">
                      <PlusIcon />
                      Add automation
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start">
                    <DropdownMenuLabel>Start from</DropdownMenuLabel>
                    {PRESETS.map((preset) => (
                      <DropdownMenuItem key={preset.id} onSelect={() => setEditing({ body: preset.body })}>
                        {preset.label}
                      </DropdownMenuItem>
                    ))}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={() =>
                        setEditing({
                          body: { name: "", agent: "auto", instructions: "", events: [], schedule_hour: 7, enabled: true, max_runs_per_day: null, unattended: false },
                        })
                      }
                    >
                      Blank
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            )}
          </>
        )}
        {editing && (
          <AutomationDialog key={editing.id ?? editing.body.name} scope={scope} initial={editing} onClose={() => setEditing(null)} />
        )}
        {confirmDialog}
      </SettingsContent>
    </SettingsSection>
  );
}

function toBody(a: Automation): AutomationCreate {
  return {
    name: a.name,
    agent: a.agent,
    instructions: a.instructions,
    events: a.events,
    schedule_hour: a.schedule_hour,
    schedule_weekday: a.schedule_weekday,
    enabled: a.enabled,
    max_runs_per_day: a.max_runs_per_day,
    unattended: a.unattended,
  };
}

type Schedule = "none" | "daily" | "weekly";

function AutomationDialog({
  scope,
  initial,
  onClose,
}: {
  scope: Scope;
  initial: { id?: string; body: AutomationCreate };
  onClose: () => void;
}) {
  const save = useSaveAutomation(scope);
  const agents = useChatAgents(scope);
  const [body, setBody] = useState<AutomationCreate>(initial.body);
  const [error, setError] = useState<string | null>(null);
  const schedule: Schedule =
    body.schedule_hour === null || body.schedule_hour === undefined
      ? "none"
      : body.schedule_weekday === null || body.schedule_weekday === undefined
        ? "daily"
        : "weekly";
  const events = body.events ?? [];

  function set(patch: Partial<AutomationCreate>) {
    setBody((b) => ({ ...b, ...patch }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await save.mutateAsync({ id: initial.id, body });
      toast.success(initial.id ? "Automation saved" : "Automation added");
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{initial.id ? "Edit automation" : "Add automation"}</DialogTitle>
          <DialogDescription>Its runs are instructed by you, and anything they change waits for approval.</DialogDescription>
        </DialogHeader>
        <form id="automation-form" onSubmit={onSubmit} className="grid gap-4">
          <FormError message={error} />
          <div className="grid gap-2">
            <Label htmlFor="automation-name">Name</Label>
            <Input id="automation-name" value={body.name} onChange={(e) => set({ name: e.target.value })} required maxLength={100} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="automation-agent">Agent</Label>
            <select
              id="automation-agent"
              value={body.agent}
              onChange={(e) => set({ agent: e.target.value })}
              className="bg-background h-9 rounded-md border px-2 text-sm"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="automation-instructions">What it does each time</Label>
            <Textarea
              id="automation-instructions"
              value={body.instructions}
              onChange={(e) => set({ instructions: e.target.value })}
              rows={4}
              required
              maxLength={4000}
              placeholder="As you'd ask it in Chat"
            />
          </div>
          <fieldset className="grid gap-2">
            <legend className="mb-1 text-sm font-medium">When something happens</legend>
            {(Object.keys(EVENT_LABELS) as AutomationEvent[]).map((event) => (
              <Label key={event} className="flex items-center gap-2 text-sm font-normal">
                <Checkbox
                  checked={events.includes(event)}
                  onCheckedChange={(c) => set({ events: c === true ? [...events, event] : events.filter((x) => x !== event) })}
                />
                {EVENT_LABELS[event]}
              </Label>
            ))}
          </fieldset>
          <div className="grid gap-2">
            <Label htmlFor="automation-schedule">On a schedule</Label>
            <div className="flex flex-wrap gap-2">
              <select
                id="automation-schedule"
                value={schedule}
                onChange={(e) => {
                  const next = e.target.value as Schedule;
                  set({
                    schedule_hour: next === "none" ? null : (body.schedule_hour ?? 7),
                    schedule_weekday: next === "weekly" ? (body.schedule_weekday ?? 0) : null,
                  });
                }}
                className="bg-background h-9 rounded-md border px-2 text-sm"
              >
                <option value="none">No schedule</option>
                <option value="daily">Every day</option>
                <option value="weekly">Every week</option>
              </select>
              {schedule === "weekly" && (
                <select
                  aria-label="Day"
                  value={body.schedule_weekday ?? 0}
                  onChange={(e) => set({ schedule_weekday: Number(e.target.value) })}
                  className="bg-background h-9 rounded-md border px-2 text-sm"
                >
                  {WEEKDAYS.map((day, i) => (
                    <option key={day} value={i}>
                      {day}
                    </option>
                  ))}
                </select>
              )}
              {schedule !== "none" && (
                <select
                  aria-label="Hour (UTC)"
                  value={body.schedule_hour ?? 7}
                  onChange={(e) => set({ schedule_hour: Number(e.target.value) })}
                  className="bg-background h-9 rounded-md border px-2 text-sm"
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, "0")}:00 UTC
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="automation-limit">Runs a day at most (empty: no limit)</Label>
            <Input
              id="automation-limit"
              type="number"
              min={1}
              max={1000}
              value={body.max_runs_per_day ?? ""}
              onChange={(e) => set({ max_runs_per_day: Number(e.target.value) || null })}
              className="w-24"
            />
          </div>
        </form>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="automation-form" disabled={save.isPending || (events.length === 0 && schedule === "none")}>
            {initial.id ? "Save" : "Add automation"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
