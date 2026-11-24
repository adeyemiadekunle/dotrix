"use client";

import { SmilePlusIcon } from "lucide-react";
import type { ComponentProps, ReactElement, RefObject } from "react";
import { useMemo, useRef, useState } from "react";
import { Button } from "@dotrix/ui/components/button";
import { Popover, PopoverPopup, PopoverTrigger } from "./ui/popover";
import { ToolbarButton } from "./ui/toolbar";
import { Tooltip, TooltipPopup, TooltipTrigger } from "./ui/tooltip";
import { useChatPopupDismissal } from "./hooks/use-chat-popup-dismissal";

export type ChatReactionPickerProps = {
  inToolbar?: boolean;
  options: readonly { emoji: string; label: string }[];
  selectedEmojis: readonly string[];
  triggerLabel: string;
  triggerTooltip: string;
  popupLabel: string;
  popupAlign?: ComponentProps<typeof PopoverPopup>["align"];
  popupAnchor?: ComponentProps<typeof PopoverPopup>["anchor"] | RefObject<HTMLElement | null>;
  onSelect: (emoji: string) => void;
};

export function ChatReactionPicker({
  inToolbar = false,
  options,
  selectedEmojis,
  triggerLabel,
  triggerTooltip,
  popupLabel,
  popupAlign,
  popupAnchor,
  onSelect,
}: ChatReactionPickerProps): ReactElement {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupAnchorAnchor = useMemo(
    () =>
      popupAnchor && typeof popupAnchor === "object" && "current" in popupAnchor
        ? {
            getBoundingClientRect: () => popupAnchor.current?.getBoundingClientRect() ?? new DOMRect(),
          }
        : popupAnchor,
    [popupAnchor],
  );

  useChatPopupDismissal(open, triggerRef, () => setOpen(false));

  const trigger = (
    <PopoverTrigger
      ref={triggerRef}
      render={
        <Button
          size="icon-xs"
          variant="ghost"
          className="pointer-coarse:size-8 rounded-full before:rounded-full"
          aria-label={triggerLabel}
          onMouseDown={(event) => {
            if (event.button === 0) event.preventDefault();
          }}
        />
      }
    />
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger render={inToolbar ? <ToolbarButton render={trigger} /> : trigger}>
          <SmilePlusIcon aria-hidden="true" className="size-3.5" />
        </TooltipTrigger>
        <TooltipPopup>{triggerTooltip}</TooltipPopup>
      </Tooltip>
      <PopoverPopup
        anchor={popupAnchorAnchor}
        side="top"
        align={popupAlign}
        aria-label={popupLabel}
        initialFocus="auto"
        className="transform-gpu rounded-full before:rounded-full **:data-[slot=popover-viewport]:p-1"
      >
        <div className="flex">
          {options.map(({ emoji, label }) => (
            <Button
              key={emoji}
              aria-label={label}
              aria-pressed={selectedEmojis.includes(emoji)}
              variant="ghost"
              size="icon-lg"
              className="rounded-full before:rounded-full"
              onMouseDown={(event) => {
                if (event.button === 0) event.preventDefault();
              }}
              onClick={() => {
                onSelect(emoji);
                setOpen(false);
              }}
            >
              <span aria-hidden="true" className="text-lg leading-none">
                {emoji}
              </span>
            </Button>
          ))}
        </div>
      </PopoverPopup>
    </Popover>
  );
}
