"use client";

import * as React from "react";
import { CircleCheckIcon, BotIcon, LoaderCircleIcon, CircleAlertIcon } from "lucide-react";

import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type SubagentStatus = "running" | "done" | "error";

function statusIcon(status: SubagentStatus) {
  if (status === "done") return <CircleCheckIcon />;
  if (status === "running") return <LoaderCircleIcon className="animate-spin" />;
  return <CircleAlertIcon />;
}

function statusTitle(name: string, status: SubagentStatus) {
  if (status === "done") return `Ran ${name}`;
  if (status === "running") return `Running ${name}`;
  return `Failed to run ${name}`;
}

/**
 * A subagent run, with its steps and result (shadcn/ui AI Elements Subagent, built on Trace).
 * `steps` is usually a Trace of ToolCall/Task rows; `report` is the subagent's summary.
 */
function Subagent({
  name,
  status,
  steps,
  report,
  defaultOpen = true,
  className,
}: {
  name: string;
  status: SubagentStatus;
  steps?: React.ReactNode;
  report?: React.ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const hasDetails = steps !== undefined || report !== undefined;
  const line = (
    <TraceLine status={status === "running" ? "running" : status === "error" ? "error" : undefined}>
      <TraceIcon>{statusIcon(status)}</TraceIcon>
      <TraceIcon>
        <BotIcon />
      </TraceIcon>
      <TraceTitle>{statusTitle(name, status)}</TraceTitle>
    </TraceLine>
  );

  if (!hasDetails) return line;

  return (
    <TraceCollapsible defaultOpen={defaultOpen} className={cn("max-w-md", className)}>
      <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <div className="flex flex-col gap-3">
          {steps && <Trace>{steps}</Trace>}
          {report}
        </div>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export { Subagent };
