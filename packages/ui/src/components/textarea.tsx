"use client";

import * as React from "react";
import { Textarea as UiTextarea } from "@ui-sdk/react/textarea";
import { cn } from "@dotrix/ui/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<typeof UiTextarea>) {
  return (
    <UiTextarea
      className={cn("input textarea flex field-sizing-content aria-invalid:border-destructive aria-invalid:shadow-[0_0_0_3px_var(--red-soft)]", className)}
      {...props}
    />
  );
}

export { Textarea };
