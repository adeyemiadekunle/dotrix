"use client";

import { ArrowUpRightIcon, GlobeIcon } from "lucide-react";

import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from "@dotrix/ui/components/trace";
import { cn } from "@dotrix/ui/lib/utils";

export type Source = {
  url: string;
  title?: string;
};

function hostname(url: string) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/**
 * The links the agent used for a reply (shadcn/ui AI Elements Sources, built on Trace).
 * One collapsible row lists every source; each opens in a new tab.
 */
function Sources({ sources, defaultOpen = true, className }: { sources: Source[]; defaultOpen?: boolean; className?: string }) {
  if (sources.length === 0) return null;
  return (
    <Trace className={cn("max-w-md", className)}>
      <TraceCollapsible defaultOpen={defaultOpen}>
        <TraceCollapsibleTrigger>
          <TraceLine>
            <TraceIcon>
              <GlobeIcon />
            </TraceIcon>
            <TraceTitle>Used {sources.length} sources</TraceTitle>
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace>
            {sources.map((source) => (
              <a key={source.url} href={source.url} target="_blank" rel="noreferrer">
                <TraceLine>
                  <TraceTitle>
                    {source.title ?? hostname(source.url)}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </TraceTitle>
                  <TraceIcon>
                    <ArrowUpRightIcon />
                  </TraceIcon>
                </TraceLine>
              </a>
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}

export { Sources };
