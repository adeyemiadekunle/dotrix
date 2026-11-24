"use client";

import * as React from "react";
import { Input as UiInput } from "@ui-sdk/react/input";
import { cn } from "@dotrix/ui/lib/utils";

type InputProps = Omit<React.ComponentProps<typeof UiInput>, "value" | "defaultValue"> & {
  value?: string | number;
  defaultValue?: string | number;
};

function Input({ className, type, value, defaultValue, ...props }: InputProps) {
  return (
    <UiInput
      type={type}
      value={value === undefined ? undefined : String(value)}
      defaultValue={defaultValue === undefined ? undefined : String(defaultValue)}
      className={cn(
        // Text field (design.css .input).
        "input min-w-0 file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-[12.5px] file:font-medium",
        "aria-invalid:border-destructive aria-invalid:shadow-[0_0_0_3px_var(--red-soft)]",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
