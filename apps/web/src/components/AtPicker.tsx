// "@" in a message box: offers the projects (where the box can change its project) and the agents;
// picking one sets it and drops the "@…" typed. Chat's composer and Home's ask box.
import { useState, type KeyboardEvent, type RefObject } from "react";

import { Ic } from "../core/icons";
import { D, proj } from "../data/store";
import { Face } from "../ui/face";
import { PIcon } from "../ui/helpers";

type Item = { kind: "project" | "agent"; id: string; label: string; sub?: string; c?: string };

export function useAtPicker({
  text,
  setText,
  ref,
  projects,
  project,
  onProject,
  agent,
  onAgent,
}: {
  text: string;
  setText: (t: string) => void;
  ref: RefObject<HTMLTextAreaElement | null>;
  projects?: [string, string][];
  project?: string;
  onProject?: (id: string) => void;
  agent: string;
  onAgent: (handle: string) => void;
}) {
  const [q, setQ] = useState<string | null>(null);
  const [hl, setHl] = useState(0);
  const ql = (q ?? "").toLowerCase();
  const items: Item[] =
    q === null
      ? []
      : [
          ...(projects && onProject ? projects.filter(([, l]) => l.toLowerCase().includes(ql)).map(([id, l]) => ({ kind: "project" as const, id, label: l })) : []),
          ...D()
            .agents.filter((x) => `${x.name} ${x.handle} ${x.role}`.toLowerCase().includes(ql))
            .map((x) => ({ kind: "agent" as const, id: x.handle, label: x.name, sub: x.role, c: x.c })),
        ];
  const choose = (it: Item) => {
    if (it.kind === "project") onProject?.(it.id);
    else onAgent(it.id);
    setText(text.replace(/(^|\s)@[\w-]*$/, "$1"));
    setQ(null);
    ref.current?.focus();
  };
  return {
    open: q !== null,
    /** The textarea's onChange. */
    onChange(el: HTMLTextAreaElement) {
      setText(el.value);
      const m = el.value.slice(0, el.selectionStart).match(/(?:^|\s)@([\w-]*)$/);
      setQ(m ? m[1]! : null);
      setHl(0);
    },
    /** Call first in the textarea's onKeyDown; true when the list used the key. */
    onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>): boolean {
      if (q === null) return false;
      if (items.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        setHl((hl + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
        return true;
      }
      if (items.length && ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab")) {
        e.preventDefault();
        choose(items[hl]!);
        return true;
      }
      if (e.key === "Escape") {
        e.stopPropagation();
        setQ(null);
        return true;
      }
      return false;
    },
    /** Types "@" and opens the list (a pill's click). */
    start() {
      setText(text + (text && !text.endsWith(" ") ? " @" : "@"));
      setQ("");
      setHl(0);
      ref.current?.focus();
    },
    menu:
      q === null ? null : (
        <div className="pop" role="listbox" aria-label={onProject ? "Projects and agents" : "Agents"} style={{ position: "absolute", top: "calc(100% + 4px)", left: 0, minWidth: 260, maxHeight: 300, overflowY: "auto", zIndex: 5, textAlign: "left" }}>
          {items.length ? (
            items.map((it, i) => (
              <div key={it.kind + it.id}>
                {(i === 0 || items[i - 1]!.kind !== it.kind) && (
                  <div className="faint" style={{ fontSize: 11, padding: "6px 10px 2px", fontWeight: 500 }}>
                    {it.kind === "project" ? "Project" : "Agent"}
                  </div>
                )}
                <button role="option" aria-selected={i === hl} className={`mi ${i === hl ? "hl" : ""}`} style={{ width: "100%" }} onMouseEnter={() => setHl(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => choose(it)}>
                  {it.kind === "agent" ? <Face c={it.c!} size={16} mood="idle" /> : it.id ? <PIcon p={proj(it.id)!} s={12} /> : <Ic n="layers" s={13} />}
                  <span className="trunc" style={{ flex: 1 }}>
                    {it.label}
                  </span>
                  {it.sub && <span className="r">{it.sub}</span>}
                  {((it.kind === "project" && it.id === project) || (it.kind === "agent" && it.id === agent)) && <Ic n="check" s={13} />}
                </button>
              </div>
            ))
          ) : (
            <div className="faint" style={{ padding: "8px 10px", fontSize: 12.5 }}>
              Nothing matches.
            </div>
          )}
        </div>
      ),
  };
}
