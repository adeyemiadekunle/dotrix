"use client";

import * as React from "react";
import { Collapsible as UiCollapsible, CollapsiblePanel as UiCollapsiblePanel, CollapsibleTrigger as UiCollapsibleTrigger } from "@ui-sdk/react/collapsible";
import { Slot } from "radix-ui";

type CollapsibleProps = Omit<React.ComponentProps<typeof UiCollapsible>, "onOpenChange"> & {
  onOpenChange?: (open: boolean) => void;
};

function Collapsible({ onOpenChange, ...props }: CollapsibleProps) {
  return <UiCollapsible onOpenChange={onOpenChange ? (open) => onOpenChange(open) : undefined} {...props} />;
}

type CollapsibleTriggerProps = Omit<React.ComponentProps<typeof UiCollapsibleTrigger>, "children"> & {
  asChild?: boolean;
  children?: React.ReactNode;
};

function CollapsibleTrigger({ asChild = false, children, render, ...props }: CollapsibleTriggerProps) {
  if (asChild) {
    if (React.isValidElement(children)) {
      return <UiCollapsibleTrigger render={children} {...props} />;
    }
    return (
      <Slot.Root data-slot="collapsible-trigger" {...(props as React.ComponentProps<typeof Slot.Root>)}>
        {children}
      </Slot.Root>
    );
  }

  return (
    <UiCollapsibleTrigger render={render} {...props}>
      {children}
    </UiCollapsibleTrigger>
  );
}

function CollapsibleContent({ ...props }: Omit<React.ComponentProps<typeof UiCollapsiblePanel>, "children"> & { children?: React.ReactNode }) {
  return <UiCollapsiblePanel {...props} />;
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
