import { useState, type ComponentProps } from "react";
import { TextInput, type TextInputType } from "@astryxdesign/core/TextInput";

export function Input({
  className,
  type = "text",
  onChange,
  disabled,
  readOnly,
  required,
  autoFocus,
  name,
  size: _size,
  autoCapitalize,
  style,
  value,
  defaultValue,
  ...props
}: ComponentProps<"input">) {
  const [draft, setDraft] = useState(String(defaultValue ?? ""));
  // File/date/number inputs retain the browser's native value and validation contract.
  if (!["text", "email", "password", "search", "tel", "url"].includes(type))
    return (
      <input
        {...props}
        className={className ? `input ${className}` : "input"}
        type={type}
        value={value}
        defaultValue={defaultValue}
        onChange={onChange}
        disabled={disabled}
        readOnly={readOnly}
        required={required}
        autoFocus={autoFocus}
        name={name}
        style={style}
      />
    );
  return (
    <TextInput
      {...props}
      data-dotrix-control
      value={value === undefined ? draft : String(value)}
      type={type as TextInputType}
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
        .filter((c) => c !== "input")
        .join(" ")}
    />
  );
}
