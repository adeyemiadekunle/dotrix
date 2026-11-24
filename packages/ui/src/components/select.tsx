"use client";

import * as React from "react";
import {
  Select as UiSelect,
  SelectContent as UiSelectContent,
  SelectGroup as UiSelectGroup,
  SelectGroupLabel as UiSelectGroupLabel,
  SelectItem as UiSelectItem,
  SelectItemIndicator as UiSelectItemIndicator,
  SelectSeparator as UiSelectSeparator,
  SelectTrigger as UiSelectTrigger,
  SelectValue as UiSelectValue,
  type ListData,
} from "@ui-sdk/react/select";
import { cn } from "@dotrix/ui/lib/utils";
import { CheckIcon, ChevronDownIcon } from "lucide-react";

type SelectProps = Omit<React.ComponentProps<typeof UiSelect<string, false>>, "onValueChange" | "multiple" | "value" | "defaultValue"> & {
  value?: string | null;
  defaultValue?: string | null;
  onValueChange?: (value: string) => void;
};

function Select({ onValueChange, ...props }: SelectProps) {
  return (
    <UiSelect<string, false>
      onValueChange={
        onValueChange
          ? (next) => {
              if (next !== null) onValueChange(next);
            }
          : undefined
      }
      {...props}
    />
  );
}

function SelectGroup({ ...props }: React.ComponentProps<typeof UiSelectGroup>) {
  return <UiSelectGroup {...props} />;
}

function SelectValue({ ...props }: React.ComponentProps<typeof UiSelectValue>) {
  return <UiSelectValue {...props} />;
}

function SelectTrigger({
  className,
  size = "default",
  variant = "default",
  children,
  ...props
}: Omit<React.ComponentProps<typeof UiSelectTrigger>, "children"> & {
  size?: "sm" | "default" | "lg";
  variant?: "default" | "ghost";
  children?: React.ReactNode;
}) {
  return (
    <UiSelectTrigger
      data-size={size}
      data-variant={variant}
      className={cn(
        "group/select-trigger inline-flex w-fit cursor-pointer items-center justify-between gap-2 text-left font-normal whitespace-nowrap text-[var(--text)] transition-[background-color,border-color,box-shadow,color] duration-150 focus-visible:border-[var(--acc)] focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-[var(--red)] data-[placeholder]:text-[var(--text-3)] *:data-[slot=select-value]:line-clamp-1 *:data-[slot=select-value]:flex *:data-[slot=select-value]:items-center *:data-[slot=select-value]:gap-2",
        size === "sm" && "h-7 gap-1.5 rounded-[7px] px-2.5 text-[12.5px]",
        size === "default" && "h-8 rounded-[8px] px-3 text-[13.5px]",
        size === "lg" && "h-9 rounded-[10px] px-3.5 text-[14px]",
        variant === "default" &&
          "border border-[var(--border-strong)] bg-[var(--surface)] shadow-[0_1px_2px_rgba(0,0,0,0.03)] hover:border-[color-mix(in_srgb,var(--border-strong)_55%,var(--text-3))] hover:bg-[color-mix(in_srgb,var(--surface-2)_45%,var(--surface))] data-[open]:border-[var(--acc)] data-[open]:ring-2 data-[open]:ring-[var(--accent-soft)]",
        variant === "ghost" && "border border-transparent bg-transparent hover:bg-[var(--surface-2)] data-[open]:bg-[var(--surface-2)]",
        className,
      )}
      {...props}
    >
      {children}
      <ChevronDownIcon
        aria-hidden="true"
        className="size-3.5 shrink-0 text-[var(--text-3)] transition-transform duration-150 group-data-[open]/select-trigger:rotate-180"
      />
    </UiSelectTrigger>
  );
}

function SelectContent({
  className,
  children,
  position = "popper",
  align = "start",
  sideOffset = 6,
  collisionPadding = 8,
  ...props
}: React.ComponentProps<typeof UiSelectContent> & {
  position?: "popper" | "item-aligned";
}) {
  return (
    <UiSelectContent
      className={cn(
        "relative z-[140] max-h-[min(320px,var(--available-height))] min-w-[max(8.5rem,var(--anchor-width))] origin-(--transform-origin) overflow-x-hidden overflow-y-auto rounded-[12px] border border-[var(--border)] bg-[var(--surface)] p-1.5 text-[var(--text)] shadow-[var(--shadow-pop)] data-[side=bottom]:slide-in-from-top-1 data-[side=left]:slide-in-from-right-1 data-[side=right]:slide-in-from-left-1 data-[side=top]:slide-in-from-bottom-1 data-[open]:animate-in data-[open]:fade-in-0 data-[open]:zoom-in-95",
        className,
      )}
      align={align}
      alignItemWithTrigger={position === "item-aligned"}
      sideOffset={sideOffset}
      collisionPadding={collisionPadding}
      {...props}
    >
      {children}
    </UiSelectContent>
  );
}

function SelectLabel({ className, ...props }: React.ComponentProps<typeof UiSelectGroupLabel>) {
  return <UiSelectGroupLabel className={cn("px-2.5 py-1.5 text-[11px] font-semibold tracking-[0.02em] text-[var(--text-3)]", className)} {...props} />;
}

function SelectItem({
  className,
  children,
  ...props
}: Omit<React.ComponentProps<typeof UiSelectItem<string>>, "children"> & {
  children?: React.ReactNode;
}) {
  return (
    <UiSelectItem
      className={cn(
        "relative flex min-h-[30px] w-full cursor-pointer items-center gap-2 rounded-[7px] py-1.5 pr-8 pl-2.5 text-[13px] text-[var(--text)] outline-hidden transition-colors select-none hover:bg-[var(--surface-2)] focus:bg-[var(--surface-2)] data-[highlighted]:bg-[var(--surface-2)] data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[selected]:bg-[color-mix(in_srgb,var(--acc)_8%,transparent)] data-[selected]:font-medium [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-[var(--text-3)] *:[span]:last:flex *:[span]:last:items-center *:[span]:last:gap-2",
        className,
      )}
      {...props}
    >
      {children}
      <span className="pointer-events-none absolute right-2.5 flex size-3.5 items-center justify-center">
        <UiSelectItemIndicator>
          <CheckIcon aria-hidden="true" className="size-3.5 text-[var(--acc)]" />
        </UiSelectItemIndicator>
      </span>
    </UiSelectItem>
  );
}

function SelectSeparator({ className, ...props }: React.ComponentProps<typeof UiSelectSeparator>) {
  return <UiSelectSeparator className={cn("pointer-events-none -mx-1 my-1 h-px bg-[var(--divider)]", className)} {...props} />;
}

function SelectScrollUpButton() {
  return null;
}

function SelectScrollDownButton() {
  return null;
}

const EMPTY_SENTINEL = "__dotrix_select_empty__";

type SelectFieldOption = {
  value: string;
  label: string;
  disabled?: boolean;
  icon?: React.ReactNode;
  description?: string;
};

type SelectFieldGroup = {
  label?: string;
  options: SelectFieldOption[];
};

function SelectField({
  id,
  "aria-label": ariaLabel,
  title,
  value,
  onValueChange,
  options,
  placeholder,
  size = "default",
  variant = "default",
  disabled,
  className,
  contentClassName,
  style,
}: {
  id?: string;
  "aria-label"?: string;
  title?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: (SelectFieldOption | SelectFieldGroup)[];
  placeholder?: string;
  size?: "sm" | "default" | "lg";
  variant?: "default" | "ghost";
  disabled?: boolean;
  className?: string;
  contentClassName?: string;
  style?: React.CSSProperties;
}) {
  const groups: SelectFieldGroup[] = [];
  let loose: SelectFieldOption[] = [];
  for (const entry of options) {
    if ("options" in entry) {
      if (loose.length) {
        groups.push({ options: loose });
        loose = [];
      }
      groups.push(entry);
    } else {
      loose.push(entry);
    }
  }
  if (loose.length) groups.push({ options: loose });

  const hasEmptyOption = groups.some((g) => g.options.some((o) => o.value === ""));
  const mappedValue = value === "" && hasEmptyOption ? EMPTY_SENTINEL : value;

  // Providing items on Select lets SelectValue and createAgent read choices while closed.
  const listData: ListData<string> = groups.flatMap((group) =>
    group.options.map((option) => ({
      value: option.value === "" ? EMPTY_SENTINEL : option.value,
      label: option.label,
      disabled: option.disabled,
    })),
  );

  return (
    <Select items={listData} value={mappedValue} onValueChange={(next) => onValueChange(next === EMPTY_SENTINEL ? "" : next)} disabled={disabled}>
      <SelectTrigger id={id} size={size} variant={variant} aria-label={ariaLabel} title={title} data-value={value} className={className} style={style}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent aria-label={ariaLabel} className={contentClassName}>
        {groups.map((group, groupIndex) => (
          <React.Fragment key={group.label ?? groupIndex}>
            {groupIndex > 0 && <SelectSeparator />}
            <SelectGroup>
              {group.label && <SelectLabel>{group.label}</SelectLabel>}
              {group.options.map((option) => (
                <SelectItem
                  key={option.value === "" ? EMPTY_SENTINEL : option.value}
                  value={option.value === "" ? EMPTY_SENTINEL : option.value}
                  label={option.label}
                  disabled={option.disabled}
                >
                  {option.icon}
                  {option.label}
                  {option.description && <span className="ml-1 text-[11.5px] text-[var(--text-3)]">{option.description}</span>}
                </SelectItem>
              ))}
            </SelectGroup>
          </React.Fragment>
        ))}
      </SelectContent>
    </Select>
  );
}

export {
  Select,
  SelectContent,
  SelectField,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
  type SelectFieldGroup,
  type SelectFieldOption,
};
