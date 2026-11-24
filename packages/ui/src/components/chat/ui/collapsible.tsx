"use client";

import {
  Collapsible as CollapsiblePrimitive,
  CollapsiblePanel as CollapsiblePanelPrimitive,
  CollapsibleTrigger as CollapsibleTriggerPrimitive,
} from "@ui-sdk/react/collapsible";
import type { ComponentProps, ReactElement } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export function Collapsible(props: ComponentProps<typeof CollapsiblePrimitive>): ReactElement {
  return <CollapsiblePrimitive data-slot="collapsible" {...props} />;
}

export function CollapsibleTrigger({ className, ...props }: ComponentProps<typeof CollapsibleTriggerPrimitive>): ReactElement {
  return <CollapsibleTriggerPrimitive className={className} data-slot="collapsible-trigger" {...props} />;
}

export function CollapsiblePanel({ className, ...props }: ComponentProps<typeof CollapsiblePanelPrimitive>): ReactElement {
  return (
    <CollapsiblePanelPrimitive
      className={cn("h-(--collapsible-panel-height) overflow-hidden transition-[height] duration-200 data-ending-style:h-0 data-starting-style:h-0", className)}
      data-slot="collapsible-panel"
      {...props}
    />
  );
}

export { CollapsiblePrimitive, CollapsiblePanel as CollapsibleContent };
