"use client";

import {
  Menu as MenuRoot,
  MenuCheckboxItem as MenuCheckboxItemPrimitive,
  MenuContent as MenuContentPrimitive,
  MenuGroup as MenuGroupPrimitive,
  MenuGroupLabel as MenuGroupLabelPrimitive,
  MenuItem as MenuItemPrimitive,
  MenuItemIndicator as MenuItemIndicatorPrimitive,
  MenuRadioGroup as MenuRadioGroupPrimitive,
  MenuRadioItem as MenuRadioItemPrimitive,
  MenuSeparator as MenuSeparatorPrimitive,
  MenuShortcut as MenuShortcutPrimitive,
  MenuTrigger as MenuTriggerPrimitive,
  MenuSub as MenuSubPrimitive,
  MenuSubContent as MenuSubContentPrimitive,
  MenuSubTrigger as MenuSubTriggerPrimitive,
} from "@ui-sdk/react/menu";
import type { ComponentProps, ReactElement, ReactNode } from "react";
import { cn } from "@dotrix/ui/lib/utils";

export const Menu = MenuRoot;
export const MenuTrigger = MenuTriggerPrimitive;
export const MenuCheckboxItemIndicator = MenuItemIndicatorPrimitive;
export const MenuRadioGroup = MenuRadioGroupPrimitive;
export const MenuShortcut = MenuShortcutPrimitive;

const menuItemClassName =
  "flex min-h-8 cursor-default select-none items-center gap-2 rounded-sm px-2 py-1 text-base text-foreground outline-none data-disabled:pointer-events-none data-highlighted:bg-accent data-inset:ps-8 data-[variant=destructive]:text-destructive-foreground data-highlighted:text-accent-foreground data-disabled:opacity-64 sm:min-h-7 sm:text-sm [&>svg:not([class*='opacity-'])]:opacity-80 [&>svg:not([class*='size-'])]:size-4.5 sm:[&>svg:not([class*='size-'])]:size-4 [&>svg]:pointer-events-none [&>svg]:-mx-0.5 [&>svg]:shrink-0";

export function MenuPopup({
  children,
  className,
  sideOffset = 4,
  align = "center",
  alignOffset,
  side = "bottom",
  anchor,
  ...props
}: Omit<ComponentProps<typeof MenuContentPrimitive>, "children"> & {
  children?: ReactNode;
}): ReactElement {
  return (
    <MenuContentPrimitive
      align={align}
      alignOffset={alignOffset}
      anchor={anchor}
      className={cn(
        "relative flex w-48 origin-(--transform-origin) flex-col rounded-lg border bg-popover not-dark:bg-clip-padding shadow-lg/5 outline-none before:pointer-events-none before:absolute before:inset-0 before:rounded-[calc(var(--radius-lg)-1px)] before:shadow-[0_1px_--theme(--color-black/4%)] focus:outline-none dark:before:shadow-[0_-1px_--theme(--color-white/6%)]",
        className,
      )}
      data-slot="menu-popup"
      side={side}
      sideOffset={sideOffset}
      {...props}
    >
      <div className="max-h-(--available-height) w-full overflow-y-auto p-1">{children}</div>
    </MenuContentPrimitive>
  );
}

export function MenuGroup(props: ComponentProps<typeof MenuGroupPrimitive>): ReactElement {
  return <MenuGroupPrimitive data-slot="menu-group" {...props} />;
}

export function MenuGroupLabel(props: ComponentProps<typeof MenuGroupLabelPrimitive>): ReactElement {
  return <MenuGroupLabelPrimitive className="px-2 py-1.5 text-xs text-muted-foreground" data-slot="menu-group-label" {...props} />;
}

export function MenuItem({
  className,
  inset,
  variant = "default",
  ...props
}: ComponentProps<typeof MenuItemPrimitive> & {
  inset?: boolean;
  variant?: "default" | "destructive";
}): ReactElement {
  return <MenuItemPrimitive className={cn(menuItemClassName, className)} data-inset={inset} data-slot="menu-item" data-variant={variant} {...props} />;
}

export function MenuCheckboxItem({
  className,
  children,
  ...props
}: Omit<ComponentProps<typeof MenuCheckboxItemPrimitive>, "children"> & {
  children?: ReactNode;
}): ReactElement {
  return (
    <MenuCheckboxItemPrimitive
      className={cn(
        "grid min-h-8 cursor-default grid-cols-[.75rem_1fr] items-center gap-2 rounded-sm py-1 pe-4 ps-2 text-base text-foreground outline-none data-disabled:pointer-events-none data-highlighted:bg-accent data-highlighted:text-accent-foreground data-disabled:opacity-64 sm:min-h-7 sm:text-sm [&_svg:not([class*='size-'])]:size-4.5 sm:[&_svg:not([class*='size-'])]:size-4 [&_svg]:pointer-events-none [&_svg]:shrink-0",
        className,
      )}
      data-slot="menu-checkbox-item"
      {...props}
    >
      <MenuItemIndicatorPrimitive className="col-start-1 -ms-0.5">
        <svg
          aria-hidden="true"
          fill="none"
          height="24"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
          width="24"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M5.252 12.7 10.2 18.63 18.748 5.37" />
        </svg>
      </MenuItemIndicatorPrimitive>
      <span className="col-start-2">{children}</span>
    </MenuCheckboxItemPrimitive>
  );
}

export function MenuRadioItem({
  className,
  children,
  ...props
}: Omit<ComponentProps<typeof MenuRadioItemPrimitive>, "children"> & {
  children?: ReactNode;
}): ReactElement {
  return (
    <MenuRadioItemPrimitive className={cn(menuItemClassName, "grid grid-cols-[.75rem_1fr] pe-4 ps-2", className)} data-slot="menu-radio-item" {...props}>
      <MenuItemIndicatorPrimitive className="col-start-1 -ms-0.5">
        <svg
          aria-hidden="true"
          fill="none"
          height="24"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2"
          viewBox="0 0 24 24"
          width="24"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
        </svg>
      </MenuItemIndicatorPrimitive>
      <span className="col-start-2">{children}</span>
    </MenuRadioItemPrimitive>
  );
}

export function MenuSeparator({ className, ...props }: ComponentProps<typeof MenuSeparatorPrimitive>): ReactElement {
  return <MenuSeparatorPrimitive className={cn("mx-2 my-1 h-px bg-border", className)} data-slot="menu-separator" {...props} />;
}

export function MenuSub(props: ComponentProps<typeof MenuSubPrimitive>): ReactElement {
  return <MenuSubPrimitive data-slot="menu-sub" {...props} />;
}

export function MenuSubTrigger({
  className,
  children,
  ...props
}: Omit<ComponentProps<typeof MenuSubTriggerPrimitive>, "children"> & {
  children?: ReactNode;
}): ReactElement {
  return (
    <MenuSubTriggerPrimitive className={cn(menuItemClassName, className)} data-slot="menu-sub-trigger" {...props}>
      {children}
      <svg
        aria-hidden="true"
        className="ms-auto size-4 opacity-80"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        viewBox="0 0 24 24"
        xmlns="http://www.w3.org/2000/svg"
      >
        <path d="m9 18 6-6-6-6" />
      </svg>
    </MenuSubTriggerPrimitive>
  );
}

export function MenuSubContent({
  children,
  className,
  sideOffset = 0,
  alignOffset = -4,
  ...props
}: Omit<ComponentProps<typeof MenuSubContentPrimitive>, "children"> & {
  children?: ReactNode;
}): ReactElement {
  return (
    <MenuSubContentPrimitive
      alignOffset={alignOffset}
      className={cn(
        "relative flex min-w-32 origin-(--transform-origin) flex-col rounded-lg border bg-popover not-dark:bg-clip-padding shadow-lg/5 outline-none before:pointer-events-none before:absolute before:inset-0 before:rounded-[calc(var(--radius-lg)-1px)] before:shadow-[0_1px_--theme(--color-black/4%)] data-starting-style:scale-98 data-starting-style:opacity-0 dark:before:shadow-[0_-1px_--theme(--color-white/6%)]",
        className,
      )}
      data-slot="menu-sub-content"
      sideOffset={sideOffset}
      {...props}
    >
      <div className="max-h-(--available-height) w-full overflow-y-auto p-1">{children}</div>
    </MenuSubContentPrimitive>
  );
}
