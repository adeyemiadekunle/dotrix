import { Badge as AstryxBadge } from "@astryxdesign/core/Badge";
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@dotrix/ui/lib/utils";
import { Slot } from "radix-ui";

const badgeVariants = cva(
  // Badge (design.css .badge and its colours).
  "badge w-fit shrink-0 justify-center overflow-hidden [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "accent",
        secondary: "",
        destructive: "red",
        outline: "bg-transparent text-foreground",
        ghost: "border-transparent bg-transparent",
        link: "border-transparent bg-transparent text-accent underline-offset-4 [a&]:hover:underline",
        brand: "accent",
        success: "green",
        warning: "amber",
        danger: "red",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  if (asChild) return <Slot.Root data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />;
  const { children, ...rest } = props;
  const tone = variant === "success" ? "success" : variant === "warning" ? "warning" : variant === "destructive" || variant === "danger" ? "error" : "neutral";
  return <AstryxBadge {...rest} label={children} variant={tone} className={className} />;
}

export { Badge, badgeVariants };
