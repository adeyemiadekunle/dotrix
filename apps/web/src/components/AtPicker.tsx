// Typing @ in a Chat draft offers projects and work modes.
import { useRef, useState, type KeyboardEvent, type RefObject } from "react";

import { MODE_ICONS, type WorkMode } from "@/lib/agent";
import { Ic } from "../core/icons";

type Item = { kind: "project" | "mode"; id: string; label: string };

export function useAtPicker({
  text,
  setText,
  ref,
  projects,
  project,
  onProject,
  modes,
  mode,
  onMode,
}: {
  text: string;
  setText: (t: string) => void;
  ref: RefObject<HTMLTextAreaElement | null>;
  projects?: [string, string][];
  project?: string;
  onProject?: (id: string) => void;
  modes?: [WorkMode, string, string][];
  mode?: string;
  onMode?: (m: WorkMode) => void;
}) {
  const [q, setQ] = useState<string | null>(null);
  const [hl, setHl] = useState(0);
  const mention = useRef<{ start: number; end: number } | null>(null);
  const open = q !== null;
  const ql = (q ?? "").toLowerCase();
  const items: Item[] = !open
    ? []
    : [
        ...(projects && onProject
          ? projects.filter(([, l]) => l.toLowerCase().includes(ql)).map(([id, l]) => ({ kind: "project" as const, id, label: l }))
          : []),
        ...(modes && onMode ? modes.filter(([, l]) => l.toLowerCase().includes(ql)).map(([v, l]) => ({ kind: "mode" as const, id: v, label: l })) : []),
      ];
  const close = () => {
    mention.current = null;
    setQ(null);
  };
  const choose = (it: Item) => {
    if (it.kind === "project") onProject?.(it.id);
    else onMode?.(it.id as WorkMode);
    if (mention.current) {
      const { start, end } = mention.current;
      setText(text.slice(0, start) + text.slice(end));
    }
    close();
    ref.current?.focus();
  };
  const label = items.some((i) => i.kind === "project") ? (items.some((i) => i.kind === "mode") ? "Projects and modes" : "Projects") : "Modes";
  return {
    close,
    /** The textarea's onChange. */
    onChange(el: HTMLTextAreaElement) {
      setText(el.value);
      const m = el.value.slice(0, el.selectionStart).match(/(?:^|\s)@([\w-]*)$/);
      mention.current = m ? { start: el.selectionStart - m[1]!.length - 1, end: el.selectionStart } : null;
      setQ(m ? m[1]! : null);
      setHl(0);
    },
    /** Call first in the textarea's onKeyDown; true when the list used the key. */
    onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): boolean {
      if (!open) return false;
      if (items.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        setHl((hl + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
        return true;
      }
      if (items.length && ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab")) {
        e.preventDefault();
        choose(items[hl] ?? items[0]!);
        return true;
      }
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        return true;
      }
      return false;
    },
    menu: !open ? null : (
      <>
        <span className="pick-veil" aria-hidden onClick={close} />
        <div
          className="pop"
          role="listbox"
          aria-label={label}
          style={{ position: "absolute", bottom: "calc(100% + 4px)", left: 0, minWidth: 260, maxHeight: 300, overflowY: "auto", zIndex: 80, textAlign: "left" }}
        >
          {items.length ? (
            items.map((it, i) => (
              <div key={it.kind + it.id}>
                {(i === 0 || items[i - 1]!.kind !== it.kind) && (
                  <div className="faint" style={{ fontSize: 11, padding: "6px 10px 2px", fontWeight: 500 }}>
                    {it.kind === "project" ? "Project" : "Mode"}
                  </div>
                )}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === hl}
                  className={`mi ${i === hl ? "hl" : ""}`}
                  style={{ width: "100%" }}
                  onMouseEnter={() => setHl(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(it)}
                >
                  {it.kind === "mode" ? <Ic n={MODE_ICONS[it.id as WorkMode]} s={13} /> : <Ic n={it.id ? "folder" : "layers"} s={13} />}
                  <span className="trunc" style={{ flex: 1 }}>
                    {it.label}
                  </span>
                  {((it.kind === "project" && it.id === project) || (it.kind === "mode" && it.id === mode)) && <Ic n="check" s={13} />}
                </button>
              </div>
            ))
          ) : (
            <div className="faint" style={{ padding: "8px 10px", fontSize: 12.5 }}>
              Nothing matches.
            </div>
          )}
        </div>
      </>
    ),
  };
}
