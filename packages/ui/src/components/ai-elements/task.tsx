"use client";

import * as React from "react";
import { CircleCheckIcon, LoaderCircleIcon, CircleAlertIcon } from "lucide-react";

import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type TaskStepStatus = "done" | "running" | "error";

export type TaskStep = {
  title: string;
  status: TaskStepStatus;
};

export type TaskData = {
  title: string;
  steps: TaskStep[];
};

type StepStatus = "running" | "error" | undefined;

function getStepStatus(status: TaskStepStatus, streaming: boolean): StepStatus {
  if (status === "done") return undefined;
  return status === "running" && streaming ? "running" : "error";
}

function StatusIcon({ status }: { status: StepStatus }) {
  if (status === "running") return <LoaderCircleIcon className="animate-spin" />;
  return status === "error" ? <CircleAlertIcon /> : <CircleCheckIcon />;
}

/**
 * The steps the agent takes, as it takes them (shadcn/ui AI Elements Task, built on Trace).
 * The row opens itself while a step runs and stays open afterwards unless the person closes it.
 */
function Task({ task, streaming = false, className }: { task: TaskData; streaming?: boolean; className?: string }) {
  const [open, setOpen] = React.useState<boolean>();
  const steps = task.steps.map((step) => ({ title: step.title, status: getStepStatus(step.status, streaming) }));
  const status: StepStatus = steps.some((step) => step.status === "error") ? "error" : steps.some((step) => step.status === "running") ? "running" : undefined;

  return (
    <TraceCollapsible open={open ?? status === "running"} onOpenChange={setOpen} className={cn("max-w-md", className)}>
      <TraceCollapsibleTrigger>
        <TraceLine status={status}>
          <TraceIcon>
            <StatusIcon status={status} />
          </TraceIcon>
          <TraceTitle>{task.title}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {steps.map((step) => (
            <TraceLine key={step.title} status={step.status}>
              <TraceIcon>
                <StatusIcon status={step.status} />
              </TraceIcon>
              <TraceTitle>{step.title}</TraceTitle>
            </TraceLine>
          ))}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export { Task };
