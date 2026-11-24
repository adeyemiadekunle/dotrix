"use client";

import type * as React from "react";
import { Button as UiButton, type ButtonActionDetails } from "@ui-sdk/react/button";

type ActionButtonProps = Omit<React.ComponentProps<typeof UiButton>, "onClick" | "children"> & {
  "data-tip"?: string;
  children?: React.ReactNode;
  onClick?: (event: React.MouseEvent<HTMLButtonElement>, details?: ButtonActionDetails) => unknown;
};

/** Native-button compatibility at the product boundary; actions stay product-owned. */
export function ActionButton({ children, className = "", type = "button", onClick, ...props }: ActionButtonProps) {
  const handleClick = onClick
    ? (event: React.MouseEvent<HTMLElement>, details: ButtonActionDetails) =>
        (onClick as (event: React.MouseEvent<HTMLElement>, details: ButtonActionDetails) => unknown)(event, details)
    : undefined;

  return (
    <UiButton type={type} className={className} onClick={handleClick} {...props}>
      {children}
    </UiButton>
  );
}
