import { useState, type ComponentProps } from "react";
import { Switch } from "@astryxdesign/core/Switch";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";

export function SelectionInput({
  checked,
  defaultChecked,
  onChange,
  disabled,
  required,
  name,
  className,
  type: _type,
  value: _value,
  size: _size,
  ...props
}: ComponentProps<"input">) {
  const [local, setLocal] = useState(defaultChecked ?? false);
  const { "aria-label": label, ...switchProps } = props;
  if (className?.split(/\s+/).includes("toggle"))
    return (
      <Switch
        {...switchProps}
        data-dotrix-control
        label={label ?? name ?? "Select"}
        isLabelHidden
        value={checked ?? local}
        htmlName={name}
        isDisabled={disabled}
        isRequired={required}
        onChange={(next, event) => {
          if (checked === undefined) setLocal(next);
          onChange?.(event);
        }}
      />
    );
  return (
    <CheckboxInput
      {...props}
      data-dotrix-control
      label={label ?? name ?? "Select"}
      isLabelHidden
      value={props["aria-checked"] === "mixed" ? "indeterminate" : (checked ?? local)}
      htmlName={name}
      isDisabled={disabled}
      isRequired={required}
      className={className
        ?.split(/\s+/)
        .filter((c) => c !== "check" && c !== "round")
        .join(" ")}
      onChange={(next, event) => {
        if (checked === undefined) setLocal(next);
        onChange?.(event);
      }}
    />
  );
}
