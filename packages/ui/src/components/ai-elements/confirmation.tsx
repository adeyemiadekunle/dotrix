"use client";

import * as React from "react";

import { Button } from "@dotrix/ui/components/button";
import { Item, ItemActions, ItemContent, ItemDescription, ItemMedia, ItemTitle } from "@dotrix/ui/components/item";
import { cn } from "@dotrix/ui/lib/utils";

/**
 * A prompt to approve or deny an action before it runs (shadcn/ui AI Elements Confirmation,
 * built on Item). A pending approval is a prompt, not activity, so it sits outside Trace.
 */
function Confirmation({
  title,
  description,
  icon,
  approveLabel = "Approve",
  denyLabel = "Deny",
  onApprove,
  onDeny,
  pending = false,
  disabled = false,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  approveLabel?: React.ReactNode;
  denyLabel?: React.ReactNode;
  onApprove?: () => void;
  onDeny?: () => void;
  pending?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <Item variant="outline" size="sm" className={cn("max-w-md", className)}>
      {icon !== undefined && <ItemMedia variant="icon">{icon}</ItemMedia>}
      <ItemContent>
        <ItemTitle>{title}</ItemTitle>
        {description !== undefined && <ItemDescription>{description}</ItemDescription>}
      </ItemContent>
      <ItemActions>
        {onDeny && (
          <Button size="sm" variant="outline" disabled={disabled || pending} onClick={onDeny}>
            {denyLabel}
          </Button>
        )}
        {onApprove && (
          <Button size="sm" disabled={disabled || pending} onClick={onApprove}>
            {approveLabel}
          </Button>
        )}
      </ItemActions>
    </Item>
  );
}

export { Confirmation };
