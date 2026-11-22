import type { ComponentProps } from "react";

/** Native-button compatibility at the product boundary; actions stay product-owned. */
export function ActionButton({ children, className = "", type = "button", ...props }: ComponentProps<"button"> & { "data-tip"?: string }) {
  return (
    <button type={type} className={className} {...props}>
      {children}
    </button>
  );
}
