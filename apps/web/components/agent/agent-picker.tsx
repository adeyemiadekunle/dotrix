"use client";

import { Button } from "@pmagent/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@pmagent/ui/components/dropdown-menu";
import { PlusIcon, XIcon } from "lucide-react";

import { AGENTS, agentLabel, modelName, type AgentId, type AgentOption } from "@/lib/agent";

/**
 * The chat input's + menu: who answers (Auto or one specialist) and, for a new conversation
 * only, the model it runs on (fixed once the first message is sent). The picks show as chips
 * beside it; removing one goes back to the default.
 */
export function AgentPicker({
  agent,
  onAgent,
  options = AGENTS,
  model,
  onModel,
  models,
  defaultModel,
  disabled,
}: {
  agent: AgentId;
  onAgent: (agent: AgentId) => void;
  /** Who can answer: Auto and the project's agents (built-in and custom). */
  options?: AgentOption[];
  /** The chosen model, or null for the project's. */
  model: string | null;
  /** Unset for an existing conversation (its model is fixed) or when you may not choose. */
  onModel?: (model: string | null) => void;
  models: string[];
  defaultModel: string;
  disabled?: boolean;
}) {
  const choosing = onModel !== undefined && models.some((m) => m !== defaultModel);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            size="icon"
            variant="outline"
            className="size-7 rounded-full"
            disabled={disabled}
            aria-label="Choose the agent and model"
            title="Choose the agent and model"
          >
            <PlusIcon />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="top" className="w-80">
          <DropdownMenuLabel>Who answers</DropdownMenuLabel>
          <DropdownMenuRadioGroup value={agent} onValueChange={(v) => onAgent(v as AgentId)}>
            {options.map((a) => (
              <DropdownMenuRadioItem key={a.id} value={a.id} className="items-start">
                <span className="grid gap-0.5">
                  <span>{a.name}</span>
                  <span className="text-muted-foreground text-xs">{a.description}</span>
                </span>
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          {choosing && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuLabel>
                Model <span className="text-muted-foreground font-normal">(for this whole conversation)</span>
              </DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={model ?? defaultModel}
                onValueChange={(v) => onModel(v === defaultModel ? null : v)}
              >
                {[defaultModel, ...models.filter((m) => m !== defaultModel)].map((m) => (
                  <DropdownMenuRadioItem key={m} value={m}>
                    <span className="font-mono text-xs">{modelName(m)}</span>
                    {m === defaultModel && <span className="text-muted-foreground ml-auto text-xs">project default</span>}
                  </DropdownMenuRadioItem>
                ))}
              </DropdownMenuRadioGroup>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {agent === "auto" ? (
        <Chip label="Auto" removeLabel="" />
      ) : (
        <Chip label={agentLabel(agent, options)} onRemove={disabled ? undefined : () => onAgent("auto")} removeLabel="Back to Auto" />
      )}
      {model && onModel && (
        <Chip label={modelName(model)} mono onRemove={disabled ? undefined : () => onModel(null)} removeLabel="Use the project's model" />
      )}
    </>
  );
}

function Chip({
  label,
  mono,
  onRemove,
  removeLabel,
}: {
  label: string;
  mono?: boolean;
  onRemove?: () => void;
  removeLabel: string;
}) {
  return (
    <span className="bg-brand-muted text-brand-muted-foreground inline-flex h-6 max-w-40 items-center gap-1 rounded-full px-2 text-xs font-medium has-[button]:pr-1">
      <span className={mono ? "truncate font-mono" : "truncate"}>{label}</span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`${label}: ${removeLabel.toLowerCase()}`}
          title={removeLabel}
          className="hover:bg-background/60 rounded-full p-0.5"
        >
          <XIcon className="size-3" />
        </button>
      )}
    </span>
  );
}
