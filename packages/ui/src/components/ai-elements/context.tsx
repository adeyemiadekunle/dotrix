import * as React from "react";
import { ChartColumnIcon } from "lucide-react";

import { Button } from "@dotrix/ui/components/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@dotrix/ui/components/hover-card";
import { Progress } from "@dotrix/ui/components/progress";
import { cn } from "@dotrix/ui/lib/utils";

export type ContextUsageData = {
  /** Tokens the conversation has used so far. */
  used: number;
  /** The model's context window. */
  limit: number;
  input?: number;
  output?: number;
  reasoning?: number;
};

function formatTokens(value: number) {
  if (value < 1000) return String(value);
  return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
}

/**
 * How much of the context window the conversation has used (shadcn/ui AI Elements Context,
 * built on Hover Card and Progress). `used` should include input, output and reasoning tokens.
 */
function ContextUsage({ usage, className }: { usage: ContextUsageData; className?: string }) {
  const percent = usage.limit > 0 ? Math.min(100, Math.round((usage.used / usage.limit) * 100)) : 0;
  const rows = [
    { label: "Input", value: usage.input },
    { label: "Output", value: usage.output },
    { label: "Reasoning", value: usage.reasoning },
  ].filter((row): row is { label: string; value: number } => row.value !== undefined);

  return (
    <HoverCard>
      <HoverCardTrigger asChild>
        <Button variant="outline" size="sm" className={cn("gap-1.5", className)} aria-label={`${percent}% context used`}>
          <ChartColumnIcon />
          {percent}% context
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="flex w-64 flex-col gap-3">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium">Context</span>
          <span className="text-muted-foreground">
            {formatTokens(usage.used)} / {formatTokens(usage.limit)}
          </span>
        </div>
        <Progress value={percent} aria-label="Context used" />
        {rows.length > 0 && (
          <div className="flex flex-col gap-1 text-sm">
            {rows.map((row) => (
              <div key={row.label} className="flex justify-between gap-3">
                <span className="text-muted-foreground">{row.label}</span>
                <span>{formatTokens(row.value)}</span>
              </div>
            ))}
          </div>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}

export { ContextUsage };
