import * as React from "react";
import { cn } from "@dotrix/ui/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        // Gr8r's text field (gr8r.css .input).
        "input min-w-0 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-[12.5px] file:font-medium",
        "aria-invalid:border-destructive aria-invalid:shadow-[0_0_0_3px_var(--red-soft)]",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
