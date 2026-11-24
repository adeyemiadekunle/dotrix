"use client";

import * as React from "react";
import { Button as UiButton, type ButtonActionDetails } from "@ui-sdk/react/button";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@dotrix/ui/lib/utils";
import { Slot } from "radix-ui";

// Buttons (design.css: .btn, .btn-primary, .btn-secondary, .btn-ghost, .btn-danger, sizes
// .btn-sm / .btn-lg). Icon sizes are the same button, square (.ibtn is the ghost one).
const buttonVariants = cva(
  "btn [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-[15px] focus-visible:outline-2 focus-visible:outline-primary aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default: "btn-primary",
        destructive: "btn-danger",
        outline: "btn-secondary",
        secondary: "btn-secondary",
        ghost: "btn-ghost",
        link: "h-auto! px-0! text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "",
        xs: "btn-sm h-[22px]! px-1.5! [&_svg:not([class*='size-'])]:size-3",
        sm: "btn-sm [&_svg:not([class*='size-'])]:size-3.5",
        lg: "btn-lg",
        icon: "aspect-square px-0!",
        "icon-xs": "btn-sm aspect-square h-[22px]! px-0! [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "btn-sm aspect-square px-0!",
        "icon-lg": "btn-lg aspect-square px-0!",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

type ButtonProps = Omit<React.ComponentProps<typeof UiButton>, "onClick" | "children"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    children?: React.ReactNode;
    onClick?: (event: React.MouseEvent<HTMLButtonElement>, details?: ButtonActionDetails) => unknown;
  };

function Button({ className, variant = "default", size = "default", asChild = false, children, onClick, render, ...props }: ButtonProps) {
  const classes = cn(buttonVariants({ variant, size, className }));
  const handleClick = onClick
    ? (event: React.MouseEvent<HTMLElement>, details: ButtonActionDetails) =>
        (onClick as (event: React.MouseEvent<HTMLElement>, details: ButtonActionDetails) => unknown)(event, details)
    : undefined;

  if (asChild) {
    if (React.isValidElement(children)) {
      return <UiButton data-variant={variant} data-size={size} className={classes} onClick={handleClick} render={children} {...props} />;
    }
    return (
      <Slot.Root data-slot="button" data-variant={variant} data-size={size} className={classes} {...(props as React.ComponentProps<typeof Slot.Root>)}>
        {children}
      </Slot.Root>
    );
  }

  return (
    <UiButton data-variant={variant} data-size={size} className={classes} onClick={handleClick} render={render} {...props}>
      {children}
    </UiButton>
  );
}

export { Button, buttonVariants };
export type { ButtonProps };
