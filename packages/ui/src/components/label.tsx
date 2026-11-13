import type { ComponentProps } from "react";
// Native labels retain htmlFor for browser-owned controls and rich label content.
export function Label(props: ComponentProps<"label">) {
  return <label data-slot="label" {...props} />;
}
