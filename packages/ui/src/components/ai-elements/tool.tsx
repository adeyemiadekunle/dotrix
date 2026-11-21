"use client";

import * as React from "react";
import { TerminalIcon } from "lucide-react";

import { CodeBlock } from "@dotrix/ui/components/code-block";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type ToolStatus = "running" | "done" | "error" | "denied" | "waiting";

/**
 * A tool call the agent makes, from input to output (shadcn/ui AI Elements Tool, built on
 * Trace). While it runs it is a plain line; once output or an error arrives it becomes a
 * collapsible whose content shows the result in a code block. `waiting` is a call still
 * awaiting an answer (e.g. client-side approval), not a failure.
 */
function ToolCall({
  title,
  status,
  output,
  error,
  icon,
  defaultOpen,
  className,
}: {
  /** What the line says, e.g. "Ran npm test". */
  title: string;
  status: ToolStatus;
  output?: string;
  error?: string;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const glyph = icon ?? <TerminalIcon />;
  const lineStatus = status === "running" ? "running" : status === "error" ? "error" : undefined;

  if (status === "done" || status === "error") {
    const body = status === "error" ? error : output;
    const line = (
      <TraceLine status={lineStatus}>
        <TraceIcon>{glyph}</TraceIcon>
        <TraceTitle>{title}</TraceTitle>
      </TraceLine>
    );
    if (body === undefined) return line;
    return (
      <TraceCollapsible defaultOpen={defaultOpen} className={className}>
        <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <CodeBlock code={body} className="max-h-64 overflow-y-auto" />
        </TraceCollapsibleContent>
      </TraceCollapsible>
    );
  }

  return (
    <TraceLine status={status === "running" ? "running" : "pending"} className={cn(className)}>
      <TraceIcon>{glyph}</TraceIcon>
      <TraceTitle>{title}</TraceTitle>
    </TraceLine>
  );
}

/** A column of tool calls, the usual place ToolCall rows live. */
function ToolCalls({ children, className }: { children: React.ReactNode; className?: string }) {
  return <Trace className={className}>{children}</Trace>;
}

export { ToolCall, ToolCalls };
