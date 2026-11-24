"use client";

import {
  ScrollArea as ScrollAreaPrimitiveRoot,
  ScrollAreaContent as ScrollAreaContentPrimitive,
  ScrollAreaCorner as ScrollAreaCornerPrimitive,
  ScrollAreaScrollbar as ScrollAreaScrollbarPrimitive,
  ScrollAreaThumb as ScrollAreaThumbPrimitive,
  ScrollAreaViewport as ScrollAreaViewportPrimitive,
} from "@ui-sdk/react/scroll-area";
import type { ComponentProps, ReactElement } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export function ScrollArea({
  className,
  children,
  scrollFade = false,
  scrollbarGutter = false,
  fill = false,
  clampContentMinWidth = true,
  overscrollContain = false,
  ...props
}: ComponentProps<typeof ScrollAreaPrimitiveRoot> & {
  scrollFade?: boolean;
  scrollbarGutter?: boolean;
  fill?: boolean;
  clampContentMinWidth?: boolean;
  overscrollContain?: boolean;
}): ReactElement {
  return (
    <ScrollAreaPrimitiveRoot className={cn("size-full min-h-0", className)} {...props}>
      <ScrollAreaViewportPrimitive
        className={cn(
          "h-full rounded-[inherit] outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background",
          overscrollContain && "data-overflow-y:overscroll-y-contain [data-overflow-x]:overscroll-x-contain",
          scrollFade &&
            "[--scroll-area-overflow-y-start:inherit] [--scroll-area-overflow-y-end:inherit] [--scroll-area-overflow-x-start:inherit] [--scroll-area-overflow-x-end:inherit] mask-t-from-[calc(100%-min(var(--fade-size),var(--scroll-area-overflow-y-start)))] mask-b-from-[calc(100%-min(var(--fade-size),var(--scroll-area-overflow-y-end)))] mask-l-from-[calc(100%-min(var(--fade-size),var(--scroll-area-overflow-x-start)))] mask-r-from-[calc(100%-min(var(--fade-size),var(--scroll-area-overflow-x-end)))] [--fade-size:1.5rem]",
          scrollbarGutter && "data-overflow-y:pe-2.5 data-overflow-x:pb-2.5",
        )}
        data-slot="scroll-area-viewport"
      >
        <ScrollAreaContentPrimitive
          className={cn(fill && "size-full")}
          data-slot="scroll-area-content"
          style={clampContentMinWidth ? { minWidth: 0 } : undefined}
        >
          {children}
        </ScrollAreaContentPrimitive>
      </ScrollAreaViewportPrimitive>
      <ScrollBar orientation="vertical" />
      <ScrollBar orientation="horizontal" />
      <ScrollAreaCornerPrimitive data-slot="scroll-area-corner" />
    </ScrollAreaPrimitiveRoot>
  );
}

export function ScrollBar({ className, orientation = "vertical", ...props }: ComponentProps<typeof ScrollAreaScrollbarPrimitive>): ReactElement {
  return (
    <ScrollAreaScrollbarPrimitive
      className={cn(
        "m-1 flex opacity-0 transition-opacity duration-100 data-visible:opacity-100 data-[orientation=horizontal]:h-1.5 data-[orientation=vertical]:w-1.5 data-[orientation=horizontal]:flex-col",
        className,
      )}
      data-slot="scroll-area-scrollbar"
      orientation={orientation}
      {...props}
    >
      <ScrollAreaThumbPrimitive className="relative flex-1 rounded-full bg-foreground/20" data-slot="scroll-area-thumb" />
    </ScrollAreaScrollbarPrimitive>
  );
}

export const ScrollAreaPrimitive = {
  Root: ScrollAreaPrimitiveRoot,
  Viewport: ScrollAreaViewportPrimitive,
  Content: ScrollAreaContentPrimitive,
  Corner: ScrollAreaCornerPrimitive,
};
