"use client";

import {
  Popover as PopoverRoot,
  PopoverClose as PopoverClosePrimitive,
  PopoverContent as PopoverContentPrimitive,
  PopoverTrigger as PopoverTriggerPrimitive,
} from "@ui-sdk/react/popover";
import type { ComponentProps, ReactElement, ReactNode } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export const Popover = PopoverRoot;
export const PopoverTrigger = PopoverTriggerPrimitive;

export function PopoverPopup({
  children,
  className,
  side = "bottom",
  align = "center",
  sideOffset = 4,
  alignOffset = 0,
  tooltipStyle = false,
  ...props
}: Omit<ComponentProps<typeof PopoverContentPrimitive>, "children"> & {
  children?: ReactNode;
  tooltipStyle?: boolean;
}): ReactElement {
  return (
    <PopoverContentPrimitive
      align={align}
      alignOffset={alignOffset}
      side={side}
      sideOffset={sideOffset}
      className={cn(
        "relative flex rounded-lg border bg-popover not-dark:bg-clip-padding text-popover-foreground shadow-lg/5 outline-none transition-[scale,opacity] before:pointer-events-none before:absolute before:inset-0 before:rounded-[calc(var(--radius-lg)-1px)] before:shadow-[0_1px_--theme(--color-black/4%)] data-starting-style:scale-98 data-starting-style:opacity-0 dark:before:shadow-[0_-1px_--theme(--color-white/6%)]",
        tooltipStyle && "w-fit text-balance rounded-md text-xs shadow-md/5 before:rounded-[calc(var(--radius-md)-1px)]",
        className,
      )}
      data-slot="popover-popup"
      {...props}
    >
      <div className={cn("relative size-full overflow-y-auto p-4", tooltipStyle && "p-1")} data-slot="popover-viewport">
        {children}
      </div>
    </PopoverContentPrimitive>
  );
}

export const PopoverClose = PopoverClosePrimitive;

export { PopoverPopup as PopoverContent };
