"use client";

import * as React from "react";
import { CircleCheckIcon, LoaderCircleIcon, CircleAlertIcon } from "lucide-react";

import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type ChainOfThoughtStatus = "running" | "error" | undefined;

function StatusIcon({ status }: { status: ChainOfThoughtStatus }) {
  if (status === "running") return <LoaderCircleIcon className="animate-spin" />;
  return status === "error" ? <CircleAlertIcon /> : <CircleCheckIcon />;
}

/**
 * One step inside a ChainOfThought: a TraceLine, or a collapsible line when it has detail.
 */
function ThoughtStep({
  title,
  status,
  defaultOpen,
  children,
  className,
}: {
  title: React.ReactNode;
  status?: ChainOfThoughtStatus;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  className?: string;
}) {
  const line = (
    <TraceLine status={status} className={className}>
      <TraceIcon>
        <StatusIcon status={status} />
      </TraceIcon>
      <TraceTitle>{title}</TraceTitle>
    </TraceLine>
  );

  if (!children) return line;

  return (
    <TraceCollapsible defaultOpen={defaultOpen}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>{children}</TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/**
 * A summary that expands into the steps an agent took (shadcn/ui AI Elements Chain of
 * Thought, built on Trace). Open while it works; afterwards a one-line summary like
 * "Researched in 4 steps".
 */
function ChainOfThought({
  title,
  running = false,
  failed = 0,
  doneLabel,
  defaultOpen,
  children,
  className,
}: {
  /** e.g. "Researching" while running. */
  title?: string;
  running?: boolean;
  /** How many steps failed, for the summary line. */
  failed?: number;
  /** Summary once finished, e.g. "Researched in 4 steps". */
  doneLabel?: string;
  defaultOpen?: boolean;
  children?: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = React.useState<boolean>();
  const status: ChainOfThoughtStatus = running ? "running" : failed > 0 ? "error" : undefined;
  const steps = React.Children.count(children);
  const summary = doneLabel ?? `Finished in ${steps} step${steps === 1 ? "" : "s"}${failed > 0 ? `, ${failed} failed` : ""}`;

  const line = (
    <TraceLine status={status}>
      <TraceIcon>
        <StatusIcon status={status} />
      </TraceIcon>
      <TraceTitle>{running ? (title ?? "Working") : summary}</TraceTitle>
    </TraceLine>
  );

  return (
    <Trace className={cn("max-w-md", className)}>
      <TraceCollapsible open={open ?? defaultOpen ?? running} onOpenChange={setOpen}>
        <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>{children}</Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

export { ChainOfThought, ThoughtStep };
