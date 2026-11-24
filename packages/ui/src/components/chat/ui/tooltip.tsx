"use client";

import { Tooltip as TooltipRoot, TooltipContent as TooltipContentPrimitive, TooltipTrigger as TooltipTriggerPrimitive } from "@ui-sdk/react/tooltip";
import type { ComponentProps, ReactElement } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export const Tooltip = TooltipRoot;
export const TooltipTrigger = TooltipTriggerPrimitive;

export function TooltipPopup({
  className,
  align = "center",
  sideOffset = 4,
  side = "top",
  ...props
}: ComponentProps<typeof TooltipContentPrimitive>): ReactElement {
  return (
    <TooltipContentPrimitive
      align={align}
      side={side}
      sideOffset={sideOffset}
      className={cn(
        "relative flex text-balance rounded-md border bg-popover not-dark:bg-clip-padding text-popover-foreground text-xs shadow-md/5 outline-none transition-[scale,opacity] before:pointer-events-none before:absolute before:inset-0 before:rounded-[calc(var(--radius-md)-1px)] before:shadow-[0_1px_--theme(--color-black/4%)] data-ending-style:scale-98 data-starting-style:scale-98 data-ending-style:opacity-0 data-starting-style:opacity-0 data-instant:duration-0 dark:before:shadow-[0_-1px_--theme(--color-white/6%)]",
        className,
      )}
      data-slot="tooltip-popup"
      {...props}
    />
  );
}

export { TooltipPopup as TooltipContent };
