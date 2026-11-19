import { useState, type ComponentProps } from "react";
import { TextArea } from "@astryxdesign/core/TextArea";

export function Textarea({
  className,
  onChange,
  disabled,
  readOnly,
  required,
  autoFocus,
  name,
  autoCapitalize,
  style,
  value,
  defaultValue,
  ...props
}: ComponentProps<"textarea">) {
  const [draft, setDraft] = useState(String(defaultValue ?? ""));
  return (
    <TextArea
      {...props}
      data-dotrix-control
      value={value === undefined ? draft : String(value)}
      label={props["aria-label"] ?? props.placeholder ?? name ?? "Text"}
      isLabelHidden
      htmlName={name}
      isDisabled={disabled}
      isReadOnly={readOnly}
      isRequired={required}
      hasAutoFocus={autoFocus}
      autoCapitalize={
        autoCapitalize === "characters" ? "characters" : autoCapitalize === "words" ? "words" : autoCapitalize === "sentences" ? "sentences" : "none"
      }
      onChange={(next, event) => {
        if (value === undefined) setDraft(next);
        onChange?.(event);
      }}
      containerStyle={style}
      controlClassName={className
        ?.split(/\s+/)
        .filter((c) => c !== "input" && c !== "textarea")
        .join(" ")}
    />
  );
}
