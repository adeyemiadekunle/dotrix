import type { ComponentProps } from "react";

/** Checkbox or switch, styled by the design system's `.check`/`.toggle` rules. */
export function SelectionInput({ className = "", type: _type, ...props }: ComponentProps<"input">) {
  const classes = className.split(/\s+/).filter(Boolean);
  const styled = classes.some((c) => c === "toggle" || c === "check" || c === "round");
  return <input type="checkbox" className={styled ? className : ["check", className].filter(Boolean).join(" ")} {...props} />;
}
