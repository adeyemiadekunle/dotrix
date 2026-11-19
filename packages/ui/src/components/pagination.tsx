// shadcn/ui's pagination (https://ui.shadcn.com/docs/components/pagination), with buttons rather
// than links, for pages a single-page app loads itself.
import { CaretLeftIcon, CaretRightIcon, DotsThreeIcon } from "@phosphor-icons/react";
import * as React from "react";

import { buttonVariants } from "@dotrix/ui/components/button";
import { cn } from "@dotrix/ui/lib/utils";

function Pagination({ className, ...props }: React.ComponentProps<"nav">) {
  return <nav role="navigation" aria-label="Pages" data-slot="pagination" className={cn("flex justify-center", className)} {...props} />;
}

function PaginationContent({ className, ...props }: React.ComponentProps<"ul">) {
  return <ul data-slot="pagination-content" className={cn("flex flex-row items-center gap-1", className)} {...props} />;
}

function PaginationItem(props: React.ComponentProps<"li">) {
  return <li data-slot="pagination-item" {...props} />;
}

type PaginationButtonProps = { isActive?: boolean } & React.ComponentProps<"button">;

function PaginationButton({ className, isActive, ...props }: PaginationButtonProps) {
  return (
    <button
      type="button"
      aria-current={isActive ? "page" : undefined}
      data-slot="pagination-link"
      data-active={isActive}
      className={cn(buttonVariants({ variant: isActive ? "outline" : "ghost", size: "icon-sm" }), "tabular-nums", className)}
      {...props}
    />
  );
}

function PaginationPrevious({ className, ...props }: React.ComponentProps<"button">) {
  return (
    <PaginationButton aria-label="Previous page" className={cn("aspect-auto! w-auto gap-1 px-2.5!", className)} {...props}>
      <CaretLeftIcon />
      <span className="hidden sm:block">Previous</span>
    </PaginationButton>
  );
}

function PaginationNext({ className, ...props }: React.ComponentProps<"button">) {
  return (
    <PaginationButton aria-label="Next page" className={cn("aspect-auto! w-auto gap-1 px-2.5!", className)} {...props}>
      <span className="hidden sm:block">Next</span>
      <CaretRightIcon />
    </PaginationButton>
  );
}

function PaginationEllipsis({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span aria-hidden data-slot="pagination-ellipsis" className={cn("flex size-8 items-center justify-center text-muted-foreground", className)} {...props}>
      <DotsThreeIcon />
    </span>
  );
}

export { Pagination, PaginationContent, PaginationItem, PaginationButton, PaginationPrevious, PaginationNext, PaginationEllipsis };
