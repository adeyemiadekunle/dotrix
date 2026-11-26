import { ActionButton } from "@dotrix/ui/components/action-button";
import { ChatScroller } from "@dotrix/ui/components/chat-scroller";
import type { PromptStatus } from "@dotrix/ui/components/prompt-input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@dotrix/ui/components/select";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { Ic } from "../core/icons";

export function InlineCode({ children, className = "", ...props }: ComponentProps<"code">) {
  return (
    <code className={`inline-code ${className}`.trim()} {...props}>
      {children}
    </code>
  );
}

export function ChatLayout({
  className = "",
  density,
  composer,
  children,
}: {
  className?: string;
  density?: string;
  composer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={`dotrix-chat-layout ${className}`.trim()} data-density={density}>
      {children}
      {composer}
    </div>
  );
}

export function ChatMessageList({ children, followKey }: { children: ReactNode; followKey?: unknown }) {
  return (
    <ChatScroller className="chat-scroll" followKey={followKey}>
      {children}
    </ChatScroller>
  );
}

type SelectorOption = { value: string; label: string };
type SelectorSection = { type: "section"; title?: string; options: SelectorOption[] } | SelectorOption[];

export function Selector({
  label,
  value,
  onChange,
  options,
  hasSearch,
  size,
  variant = "default",
}: {
  label: string;
  isLabelHidden?: boolean;
  value: string;
  onChange: (value: string) => void;
  options: SelectorSection[];
  hasSearch?: boolean;
  size?: "sm" | "default" | "lg" | string;
  variant?: "default" | "ghost";
}) {
  const sections = useMemo(() => options.map((section) => (Array.isArray(section) ? { title: undefined, options: section } : section)), [options]);
  const allOptions = useMemo(() => sections.flatMap((section) => section.options), [sections]);
  const searchable = Boolean(hasSearch && allOptions.length > 8);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [coords, setCoords] = useState<CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listId = useId();

  const filteredSections = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return sections;
    return sections
      .map((section) => ({
        ...section,
        options: section.options.filter((option) => option.label.toLowerCase().includes(q) || option.value.toLowerCase().includes(q)),
      }))
      .filter((section) => section.options.length > 0);
  }, [query, sections]);

  const flatFiltered = useMemo(() => filteredSections.flatMap((section) => section.options), [filteredSections]);
  const selectedLabel = allOptions.find((option) => option.value === value)?.label ?? value;

  const updatePlacement = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const spaceBelow = window.innerHeight - rect.bottom - 12;
    const spaceAbove = rect.top - 12;
    const above = spaceBelow < 220 && spaceAbove > spaceBelow;
    const maxWidth = window.innerWidth - 16;
    const width = Math.min(Math.max(rect.width, 220), maxWidth);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8));
    setCoords({
      position: "fixed",
      left,
      minWidth: width,
      maxWidth: Math.min(340, maxWidth),
      maxHeight: Math.min(320, Math.max(120, above ? spaceAbove : spaceBelow)),
      zIndex: 140,
      ...(above ? { bottom: window.innerHeight - rect.top + 6 } : { top: rect.bottom + 6 }),
    });
  }, []);

  useEffect(() => {
    if (!searchable || !open) return;
    updatePlacement();
    requestAnimationFrame(() => searchRef.current?.focus());
    const onDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (triggerRef.current?.contains(target) || popRef.current?.contains(target)) return;
      setOpen(false);
      setQuery("");
    };
    const onResize = () => updatePlacement();
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onResize, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
    };
  }, [open, searchable, updatePlacement]);

  if (!searchable) {
    return (
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger size={size === "sm" ? "sm" : size === "lg" ? "lg" : "default"} variant={variant} aria-label={label}>
          <SelectValue placeholder={label} />
        </SelectTrigger>
        <SelectContent aria-label={label}>
          {sections.map((section, index) => (
            <SelectGroup key={section.title ?? index}>
              {index > 0 && <SelectSeparator />}
              {section.title && <SelectLabel>{section.title}</SelectLabel>}
              {section.options.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    );
  }

  const pickOption = (option: SelectorOption) => {
    onChange(option.value);
    setOpen(false);
    setQuery("");
    triggerRef.current?.focus();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        role="combobox"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        data-size={size === "sm" ? "sm" : size === "lg" ? "lg" : "default"}
        data-variant={variant}
        className={`cmp-select-trigger ${variant === "ghost" ? "ghost" : ""} ${size === "sm" ? "sm" : ""}`}
        onClick={() => {
          setOpen((current) => !current);
          setQuery("");
          setHighlighted(0);
        }}
      >
        <span className="trunc">{selectedLabel}</span>
        <Ic n="chevron-down" s={13} cls="cmp-select-chev" />
      </button>
      {open &&
        createPortal(
          <div
            ref={popRef}
            id={listId}
            role="listbox"
            aria-label={label}
            data-dotrix-select-listbox=""
            className="cmp-select-pop"
            style={coords}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                setOpen(false);
                setQuery("");
                triggerRef.current?.focus();
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                if (flatFiltered.length) setHighlighted((current) => (current + 1) % flatFiltered.length);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                if (flatFiltered.length) setHighlighted((current) => (current - 1 + flatFiltered.length) % flatFiltered.length);
              } else if (event.key === "Enter") {
                event.preventDefault();
                const picked = flatFiltered[highlighted];
                if (picked) pickOption(picked);
              }
            }}
          >
            <div className="cmp-select-search">
              <Ic n="search" s={13} />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setHighlighted(0);
                }}
                placeholder="Search…"
                aria-label={`Search ${label}`}
              />
            </div>
            <div className="cmp-select-scroll">
              {filteredSections.length > 0 ? (
                filteredSections.map((section, sectionIndex) => (
                  <div key={section.title ?? sectionIndex} role="group">
                    {sectionIndex > 0 && <div className="composer-menu-sep" />}
                    {section.title && <div className="composer-menu-heading">{section.title}</div>}
                    {section.options.map((option) => {
                      const flatIdx = flatFiltered.indexOf(option);
                      const selected = option.value === value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          role="option"
                          aria-selected={selected}
                          className={`cmp-select-item ${flatIdx === highlighted ? "hl" : ""}`}
                          onMouseEnter={() => setHighlighted(flatIdx)}
                          onClick={() => pickOption(option)}
                        >
                          <span className="trunc">{option.label}</span>
                          {selected && <Ic n="check" s={14} cls="composer-menu-check" />}
                        </button>
                      );
                    })}
                  </div>
                ))
              ) : (
                <div className="composer-menu-note">No matches</div>
              )}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}

type ComplexSelectorProps = {
  label: string;
  isLabelHidden?: boolean;
  value: string;
  placement?: "above" | "below";
  alignment?: string;
  isDisabled?: boolean;
  onOpenChange?: (open: boolean) => void;
  renderTrigger: (props: ComponentProps<"button"> & { role?: string }) => ReactNode;
  afterTrigger?: (toggle: () => void, open: boolean) => ReactNode;
  children: ReactNode | ((value: string, change: (value: string) => void, close: () => void) => ReactNode);
};

export function ComplexSelector({ label, value, placement = "below", isDisabled, onOpenChange, renderTrigger, afterTrigger, children }: ComplexSelectorProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const close = useCallback(() => {
    setOpen(false);
    onOpenChange?.(false);
  }, [onOpenChange]);
  const toggle = useCallback(() => {
    if (isDisabled) return;
    const next = !open;
    setOpen(next);
    onOpenChange?.(next);
  }, [isDisabled, onOpenChange, open]);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element) || root.current?.contains(target)) return;
      if (target.closest('[data-radix-popper-content-wrapper], [data-slot="select-content"][data-open], [data-dotrix-select-listbox]')) {
        return;
      }
      if (document.querySelector('[data-slot="select-content"][data-open], [data-dotrix-select-listbox]')) {
        return;
      }
      const listbox = target.closest('[role="listbox"]');
      if (
        listbox?.id &&
        [...(root.current?.querySelectorAll("[aria-controls]") ?? [])].some((element) => element.getAttribute("aria-controls") === listbox.id)
      ) {
        return;
      }
      close();
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector('[data-slot="select-content"][data-open], [data-dotrix-select-listbox]')) {
        close();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [close, open]);
  return (
    <span ref={root} className="cmp-selector-root" style={{ position: "relative", display: "inline-flex", alignItems: "center", gap: 4 }}>
      {renderTrigger({
        type: "button",
        role: "button",
        "aria-label": label,
        "aria-haspopup": "dialog",
        "aria-expanded": open,
        disabled: isDisabled,
        onClick: toggle,
      })}
      {afterTrigger?.(toggle, open)}
      {open && (
        <div
          className="cmp-menu-pop"
          role="dialog"
          aria-label={label}
          style={{ position: "absolute", [placement === "above" ? "bottom" : "top"]: "calc(100% + 8px)", left: 0, zIndex: 75 }}
        >
          {typeof children === "function" ? children(value, () => undefined, close) : children}
        </div>
      )}
    </span>
  );
}

export function DesignButton({
  label,
  icon,
  isIconOnly,
  isDisabled,
  variant = "secondary",
  size = "md",
  className = "",
  children,
  ...props
}: ComponentProps<"button"> & {
  label: ReactNode;
  icon?: ReactNode;
  isIconOnly?: boolean;
  isDisabled?: boolean;
  variant?: "primary" | "secondary" | "ghost" | "destructive" | string;
  size?: "sm" | "md" | "lg" | string;
}) {
  const btnClass =
    variant === "primary" ? "btn btn-primary" : variant === "destructive" ? "btn btn-danger" : variant === "ghost" ? "btn btn-ghost" : "btn btn-secondary";
  const sizeClass = size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : "";
  if (isIconOnly)
    return (
      <ActionButton
        {...props}
        type="button"
        className={[isDisabled ? "ibtn ibtn-sm" : "ibtn", className].filter(Boolean).join(" ")}
        aria-label={typeof label === "string" ? label : undefined}
        disabled={isDisabled}
      >
        {icon ?? children}
      </ActionButton>
    );
  return (
    <ActionButton {...props} type="button" className={[btnClass, sizeClass, className].filter(Boolean).join(" ")} disabled={isDisabled}>
      {icon}
      {label}
    </ActionButton>
  );
}

export function CodingOptions({
  mode,
  setMode,
  local,
  disabled = false,
  onOpenChange,
  placement = "below",
  focusInput,
  afterTrigger,
  children,
}: {
  mode: "plan" | "build";
  setMode: (mode: "plan" | "build") => void;
  local: boolean;
  disabled?: boolean;
  onOpenChange?: (open: boolean) => void;
  placement?: "above" | "below";
  focusInput: () => void;
  afterTrigger?: (toggle: () => void, open: boolean) => ReactNode;
  children?: (close: () => void) => ReactNode;
}) {
  return (
    <ComplexSelector
      label="Code options"
      isLabelHidden
      value=""
      placement={placement}
      alignment="start"
      isDisabled={disabled}
      onOpenChange={onOpenChange}
      afterTrigger={afterTrigger}
      renderTrigger={(props) => (
        <DesignButton
          {...props}
          role="button"
          label="Code options"
          className="cmp-plus-btn"
          variant="ghost"
          size="sm"
          isIconOnly
          icon={<Ic n="plus" s={16} />}
        />
      )}
    >
      {(_value, _change, close) => (
        <div className="composer-options-menu">
          <span className="composer-menu-heading">Mode</span>
          {(["build", "plan"] as const).map((value) => (
            <DesignButton
              key={value}
              className="composer-menu-option"
              label={
                <>
                  <span>{value === "plan" ? "Plan (read only)" : "Build"}</span>
                  {mode === value && <Ic n="check" s={14} cls="composer-menu-check" />}
                </>
              }
              variant="ghost"
              aria-pressed={mode === value}
              icon={<Ic n={value === "plan" ? "list-checks" : "hammer"} s={15} />}
              isDisabled={disabled || (value === "plan" && local)}
              onClick={() => {
                setMode(value);
                close();
                focusInput();
              }}
            />
          ))}
          {children?.(close)}
        </div>
      )}
    </ComplexSelector>
  );
}

export function ChatComposerInput({
  textareaRef,
  value,
  onChange,
  placeholder,
  label,
  onKeyDown,
  isDisabled,
  status,
  pasteAsToken: _pasteAsToken,
  hasHistory: _hasHistory,
  onSubmit: _onSubmit,
  ...props
}: Omit<ComponentProps<"textarea">, "onChange" | "value"> & {
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: ComponentProps<"textarea">["onChange"];
  label?: string;
  isDisabled?: boolean;
  /** The PromptInput status model: "sending" makes the box read-only, "waiting" disables it. */
  status?: PromptStatus;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  pasteAsToken?: boolean;
  hasHistory?: boolean;
  onSubmit?: () => void;
}) {
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    if (!value) {
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [textareaRef, value]);
  return (
    <span style={{ position: "relative", display: "block", minWidth: 0 }}>
      <textarea
        {...props}
        ref={textareaRef}
        className={`composer-textarea ${props.className ?? ""}`.trim()}
        rows={1}
        value={value}
        disabled={isDisabled || status === "waiting"}
        readOnly={status === "sending"}
        placeholder={placeholder}
        aria-label={label}
        onChange={onChange}
        onKeyDown={onKeyDown}
      />
    </span>
  );
}

export function ChatComposer({
  className,
  onSubmit,
  header,
  input,
  footerActions,
  sendActions,
  sendButton,
  children,
  value,
  isDisabled: _isDisabled,
  isStopShown: _isStopShown,
  ...props
}: ComponentProps<"form"> & {
  value?: string;
  isDisabled?: boolean;
  isStopShown?: boolean;
  header?: ReactNode;
  input?: ReactNode;
  footerActions?: ReactNode;
  sendActions?: ReactNode;
  sendButton?: ReactNode;
}) {
  return (
    <form
      {...props}
      className={["dotrix-composer", "compact-composer", value ? "has-text" : "", className].filter(Boolean).join(" ")}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit?.(event);
      }}
    >
      {header && <div className="cmp-header">{header}</div>}
      <div className="cmp-body">{input}</div>
      <div className="cmp-toolbar">
        <div className="cmp-toolbar-left">{footerActions}</div>
        <div className="cmp-controls cmp-controls-right">
          {sendActions}
          {sendButton}
        </div>
      </div>
      {children}
    </form>
  );
}

export function ChatSendButton({
  onSend,
  isDisabled,
  isStopShown,
  onStop,
  status,
  ...props
}: ComponentProps<"button"> & {
  onSend?: () => void;
  isDisabled?: boolean;
  isStopShown?: boolean;
  onStop?: () => void;
  /** The PromptInput status model: "working"/"stopping" turns the button into Stop (with `onStop`),
   *  "sending" spins, "waiting" disables. */
  status?: PromptStatus;
}) {
  const stoppable = isStopShown || Boolean(onStop);
  if (stoppable)
    return (
      <button
        {...props}
        type="button"
        className="kt-send kt-stop"
        disabled={isDisabled || status === "stopping"}
        onClick={onStop}
        aria-label={props["aria-label"] ?? "Stop"}
        data-tip="Stop this turn"
      >
        <Ic n="square" s={12} />
      </button>
    );
  const sending = status === "sending";
  const inactive = status !== undefined && status !== "ready";
  return (
    <button
      {...props}
      type="button"
      className="kt-send"
      disabled={isDisabled || inactive}
      onClick={onSend}
      aria-label={props["aria-label"] ?? "Send"}
      data-tip="Send"
    >
      {sending ? <Ic n="spinner-gap" s={15} cls="animate-spin" /> : <Ic n="arrow-up" s={15} />}
    </button>
  );
}

export function Lightbox({
  isOpen,
  onOpenChange,
  media,
  hasZoom: _hasZoom,
}: {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  media?: { src: string; alt?: string; caption?: string };
  hasZoom?: boolean;
}) {
  const [zoom, setZoom] = useState(false);
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [isOpen, onOpenChange]);
  if (!isOpen || !media) return null;
  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={media.caption ?? media.alt ?? "Image"}
      onClick={() => onOpenChange(false)}
      style={{ position: "fixed", inset: 0, zIndex: 100, display: "grid", placeItems: "center", background: "rgba(0,0,0,.72)", padding: 24 }}
    >
      <figure
        onClick={(event) => event.stopPropagation()}
        style={{ margin: 0, maxWidth: "min(1200px, 100%)", maxHeight: "100%", display: "flex", flexDirection: "column", gap: 8 }}
      >
        <img
          src={media.src}
          alt={media.alt ?? ""}
          style={{
            maxWidth: "100%",
            maxHeight: "82dvh",
            objectFit: "contain",
            transform: zoom ? "scale(1.6)" : undefined,
            transformOrigin: "center",
            transition: "transform .18s ease",
            cursor: zoom ? "zoom-out" : "zoom-in",
          }}
          onClick={() => setZoom((value) => !value)}
        />
        <figcaption className="faint" style={{ textAlign: "center", fontSize: 12 }}>
          {media.caption}
        </figcaption>
      </figure>
    </div>
  );
}
