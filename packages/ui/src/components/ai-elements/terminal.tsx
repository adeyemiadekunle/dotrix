"use client";

import * as React from "react";
import { TerminalIcon } from "lucide-react";

import { CodeBlock } from "@dotrix/ui/components/code-block";
import { TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type TerminalCommandStatus = "running" | "done" | "error";

function commandTitle(command: string, status: TerminalCommandStatus, exitCode?: number) {
  if (status === "done") {
    return exitCode !== undefined && exitCode !== 0 ? `${command} exited with code ${exitCode}` : `Ran ${command}`;
  }
  return status === "running" ? `Running ${command}` : `Failed to run ${command}`;
}

/**
 * A command the agent runs, with its output (shadcn/ui AI Elements Terminal, built on Trace).
 * Opens itself while the command runs and there is output to show.
 */
function TerminalCommand({
  command,
  status,
  output,
  exitCode,
  error,
  defaultOpen,
  className,
}: {
  command: string;
  status: TerminalCommandStatus;
  output?: string;
  exitCode?: number;
  error?: string;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = React.useState<boolean>();
  const running = status === "running";
  const failed = status === "error" || (status === "done" && exitCode !== undefined && exitCode !== 0);
  const body = error ?? output;

  const line = (
    <TraceLine status={running ? "running" : failed ? "error" : undefined} className={body === undefined ? className : undefined}>
      <TraceIcon>
        <TerminalIcon />
      </TraceIcon>
      <TraceTitle>{commandTitle(command, status, exitCode)}</TraceTitle>
    </TraceLine>
  );

  if (body === undefined) {
    return line;
  }

  return (
    <TraceCollapsible open={open ?? defaultOpen ?? (running && (output?.length ?? 0) > 0)} onOpenChange={setOpen} className={cn("max-w-md", className)}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <CodeBlock code={body} className="max-h-64 overflow-y-auto" />
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export { TerminalCommand };
