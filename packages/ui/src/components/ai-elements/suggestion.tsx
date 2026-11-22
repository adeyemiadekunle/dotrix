"use client";

import type { ReactNode } from "react";

import { Button } from "@dotrix/ui/components/button";
import { cn } from "@dotrix/ui/lib/utils";

export type SuggestionItem = {
  key: string;
  /** What the button shows; a plain string works for text-only suggestions. */
  content: ReactNode;
  /** What `onSelect` reports; defaults to `key`. */
  value?: string;
};

/**
 * Short prompts you can send to the agent in one click (shadcn/ui AI Elements Suggestion).
 * A horizontally scrollable row of outline buttons above the composer.
 */
function Suggestions({
  items,
  onSelect,
  disabled = false,
  className,
}: {
  items: (string | SuggestionItem)[];
  onSelect: (value: string, item: SuggestionItem) => void;
  disabled?: boolean;
  className?: string;
}) {
  const normalized: SuggestionItem[] = items.map((item) => (typeof item === "string" ? { key: item, content: item } : item));
  if (normalized.length === 0) return null;
  return (
    <div className={cn("flex gap-2 overflow-x-auto overscroll-x-contain pb-1", className)}>
      {normalized.map((item) => (
        <Button key={item.key} variant="outline" size="sm" className="shrink-0" disabled={disabled} onClick={() => onSelect(item.value ?? item.key, item)}>
          {item.content}
        </Button>
      ))}
    </div>
  );
}

export { Suggestions };
