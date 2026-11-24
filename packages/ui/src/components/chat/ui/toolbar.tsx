"use client";

import {
  Toolbar as ToolbarPrimitive,
  ToolbarButton as ToolbarButtonPrimitive,
  ToolbarGroup as ToolbarGroupPrimitive,
  ToolbarInput as ToolbarInputPrimitive,
  ToolbarLink as ToolbarLinkPrimitive,
  ToolbarSeparator as ToolbarSeparatorPrimitive,
} from "@ui-sdk/react/toolbar";
import type { ComponentProps, ReactElement } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export function Toolbar({ className, ...props }: ComponentProps<typeof ToolbarPrimitive>): ReactElement {
  return (
    <ToolbarPrimitive
      className={cn("relative flex gap-2 rounded-xl border bg-card not-dark:bg-clip-padding p-1 text-card-foreground", className)}
      data-slot="toolbar"
      {...props}
    />
  );
}

export function ToolbarButton({ className, ...props }: ComponentProps<typeof ToolbarButtonPrimitive>): ReactElement {
  return <ToolbarButtonPrimitive className={cn(className)} data-slot="toolbar-button" {...props} />;
}

export function ToolbarLink({ className, ...props }: ComponentProps<typeof ToolbarLinkPrimitive>): ReactElement {
  return <ToolbarLinkPrimitive className={cn(className)} data-slot="toolbar-link" {...props} />;
}

export function ToolbarInput({ className, ...props }: ComponentProps<typeof ToolbarInputPrimitive>): ReactElement {
  return <ToolbarInputPrimitive className={cn(className)} data-slot="toolbar-input" {...props} />;
}

export function ToolbarGroup({ className, ...props }: ComponentProps<typeof ToolbarGroupPrimitive>): ReactElement {
  return <ToolbarGroupPrimitive className={cn("flex items-center gap-1", className)} data-slot="toolbar-group" {...props} />;
}

export function ToolbarSeparator({ className, ...props }: ComponentProps<typeof ToolbarSeparatorPrimitive>): ReactElement {
  return (
    <ToolbarSeparatorPrimitive
      className={cn(
        "shrink-0 bg-border data-[orientation=horizontal]:my-0.5 data-[orientation=vertical]:my-1.5 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:w-px data-[orientation=vertical]:not-[[class^='h-']]:not-[[class*='_h-']]:self-stretch",
        className,
      )}
      data-slot="toolbar-separator"
      {...props}
    />
  );
}
