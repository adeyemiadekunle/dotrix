import * as React from "react"
import { cn } from "@dotrix/ui/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "input textarea flex field-sizing-content aria-invalid:border-destructive aria-invalid:shadow-[0_0_0_3px_var(--red-soft)]",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
