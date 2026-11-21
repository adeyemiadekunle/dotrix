"use client";

import * as React from "react";
import { BrainIcon } from "lucide-react";

import { TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

/**
 * The agent's thinking as it streams (shadcn/ui AI Elements Reasoning, built on Trace).
 * Open while it runs; afterwards it collapses to a "Thought" line the person can reopen.
 */
function Reasoning({
  text,
  running = false,
  defaultOpen,
  label,
  className,
}: {
  text: string;
  running?: boolean;
  /** Used once the run ends; defaults to open so the thinking stays readable. */
  defaultOpen?: boolean;
  /** e.g. "Thought for 5s". Defaults to "Thinking" while running, "Thought" after. */
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState<boolean | undefined>(defaultOpen);
  const title = label ?? (running ? "Thinking" : "Thought");

  const line = (
    <TraceLine status={running ? "running" : undefined}>
      <TraceIcon>
        <BrainIcon />
      </TraceIcon>
      <TraceTitle>{title}</TraceTitle>
    </TraceLine>
  );

  if (text.length === 0) return line;

  return (
    <TraceCollapsible open={open ?? running} onOpenChange={setOpen} className={cn("max-w-md", className)}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent className="whitespace-pre-wrap">{text}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export { Reasoning };
