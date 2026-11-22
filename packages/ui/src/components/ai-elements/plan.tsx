"use client";

import * as React from "react";
import { CircleCheckIcon, CircleDashedIcon, CircleIcon, MapIcon } from "lucide-react";

import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type PlanStepStatus = "done" | "running" | "pending";

export type PlanStep = {
  title: string;
  status: PlanStepStatus;
  description?: React.ReactNode;
};

export type PlanData = {
  title: string;
  description?: React.ReactNode;
  steps: PlanStep[];
};

function StepIcon({ status }: { status: PlanStepStatus }) {
  if (status === "done") return <CircleCheckIcon />;
  if (status === "running") return <CircleDashedIcon />;
  return <CircleIcon />;
}

/**
 * The steps the agent plans to take and how far it has got (shadcn/ui AI Elements Plan,
 * built on Trace). `streaming` keeps the in-progress step shimmering until the agent stops.
 */
function Plan({ plan, streaming = false, defaultOpen = true, className }: { plan: PlanData; streaming?: boolean; defaultOpen?: boolean; className?: string }) {
  const done = plan.steps.filter((step) => step.status === "done").length;
  const running = streaming && done < plan.steps.length;

  return (
    <TraceCollapsible defaultOpen={defaultOpen} className={cn("max-w-md", className)}>
      <TraceCollapsibleTrigger>
        <TraceLine status={running ? "running" : undefined}>
          <TraceIcon>
            <MapIcon />
          </TraceIcon>
          <TraceTitle>{plan.title}</TraceTitle>
          <TraceDescription>
            {done} of {plan.steps.length} done
          </TraceDescription>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <div className="flex flex-col gap-3">
          {plan.description}
          <Trace>
            {plan.steps.map((step) => (
              <TraceLine key={step.title} status={step.status === "pending" ? "pending" : streaming && step.status === "running" ? "running" : undefined}>
                <TraceIcon>
                  <StepIcon status={step.status} />
                </TraceIcon>
                <TraceTitle>{step.title}</TraceTitle>
                {step.description && <TraceDescription>{step.description}</TraceDescription>}
              </TraceLine>
            ))}
          </Trace>
        </div>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

export { Plan };
