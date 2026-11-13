import { Children, isValidElement, type ComponentProps, type ReactNode } from "react";
import { Button as AstryxButton } from "@astryxdesign/core/Button";

function textOf(children: ReactNode): string {
  return Children.toArray(children)
    .map((child): string => {
      if (typeof child === "string" || typeof child === "number") return String(child);
      return isValidElement<{ children?: ReactNode }>(child) ? textOf(child.props.children) : "";
    })
    .join(" ")
    .trim();
}

/** Native-button compatibility at the product boundary; actions stay product-owned. */
export function ActionButton({ children, className = "", disabled, title, type = "button", ...props }: ComponentProps<"button"> & { "data-tip"?: string }) {
  const classes = className.split(/\s+/);
  const iconOnly = classes.some((c) => /^ibtn(?:-|$)|^icon-btn$/.test(c));
  const variant = classes.includes("btn-primary")
    ? "primary"
    : classes.includes("btn-danger")
      ? "destructive"
      : classes.some((c) => c === "btn-ghost" || c.startsWith("ibtn") || c === "icon-btn")
        ? "ghost"
        : "secondary";
  const size = classes.some((c) => /^(?:i?btn)-(?:xs|sm)$/.test(c)) ? "sm" : classes.includes("btn-lg") ? "lg" : "md";
  const label = props["aria-label"] ?? (textOf(children) || title || props["data-tip"] || "Action");
  const ownClasses = classes.filter((c) => !/^(?:btn|ibtn)(?:-|$)/.test(c) && c !== "icon-btn").join(" ");
  return (
    <AstryxButton
      {...props}
      type={type}
      label={label}
      variant={variant}
      size={size}
      isDisabled={disabled}
      className={ownClasses || undefined}
      tooltip={title ?? props["data-tip"]}
      isIconOnly={iconOnly}
      icon={iconOnly ? children : undefined}
    >
      {iconOnly ? undefined : <span className="dotrix-action-content">{children}</span>}
    </AstryxButton>
  );
}
