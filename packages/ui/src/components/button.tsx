import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@dotrix/ui/lib/utils";
import { Slot } from "radix-ui";

// Gr8r's buttons (gr8r.css: .btn, .btn-primary, .btn-secondary, .btn-ghost, .btn-danger, sizes
// .btn-sm / .btn-lg). Icon sizes are the same button, square (Gr8r's .ibtn is the ghost one).
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

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : "button";

  return <Comp data-slot="button" data-variant={variant} data-size={size} className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export { Button, buttonVariants };
