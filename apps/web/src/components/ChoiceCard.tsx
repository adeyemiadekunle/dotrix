// A new chat's or a new coding session's middle, as Claude Code's environment card: the first few choices
// (a project, or where Kai codes) with a tick on the one picked, and "Choose …" opening the full list, with a
// search once it's long and any extra actions (Add a folder) at its foot.
import { useMemo, useState, type ReactNode } from "react";

import { Ic } from "../core/icons";

export interface Choice {
  id: string;
  label: string;
  icon: ReactNode;
  on: boolean;
  group?: string; // a heading in the full list: "This computer", "Cloud"
  note?: string; // shown faint on the right: "Not ready", "Off"
  tip?: string;
  disabled?: boolean;
  onPick: () => void;
}

const SHOWN = 3;

export function ChoiceCard({ label, choices, extra }: { label: string; choices: Choice[]; extra?: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // The card keeps the picked one in view: the first few, with the picked one in place of the last if it's further down.
  const shown = useMemo(() => {
    const first = choices.slice(0, SHOWN);
    const on = choices.find((c) => c.on);
    return on && !first.includes(on) ? [...first.slice(0, SHOWN - 1), on] : first;
  }, [choices]);
  const found = choices.filter((c) => c.label.toLowerCase().includes(query.trim().toLowerCase()));
  const close = () => {
    setOpen(false);
    setQuery("");
  };
  const row = (c: Choice, inMenu: boolean) => (
    <button
      key={c.id}
      type="button"
      role="option"
      aria-selected={c.on}
      className={`cc-item ${c.on ? "on" : ""}`}
      disabled={c.disabled}
      data-tip={c.tip}
      onClick={() => {
        c.onPick();
        if (inMenu) close();
      }}
    >
      {c.icon}
      <span className="trunc grow">{c.label}</span>
      {c.note && <span className="faint cc-note">{c.note}</span>}
      {c.on && <Ic n="check" s={15} />}
    </button>
  );
  let group: string | undefined;
  return (
    <div className="cc">
      <div role="listbox" aria-label={label}>
        {shown.map((c) => row(c, false))}
      </div>
      <div className="cc-foot">
        <button type="button" className="cc-more" onClick={() => (open ? close() : setOpen(true))} aria-haspopup="listbox" aria-expanded={open}>
          {label}
          <Ic n="chevron-down" s={12} />
        </button>
        {open && (
          <>
            <span className="pick-veil" aria-hidden onClick={close} />
            <div className="cc-menu" role="listbox" aria-label={label} onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), close())}>
              {choices.length > 6 && (
                <input
                  className="cc-search"
                  autoFocus
                  placeholder="Search…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label={`Search: ${label}`}
                />
              )}
              {found.map((c) => {
                const head = c.group && c.group !== group ? c.group : null;
                group = c.group;
                return (
                  <div key={c.id} style={{ display: "contents" }}>
                    {head && <span className="cc-h">{head}</span>}
                    {row(c, true)}
                  </div>
                );
              })}
              {!found.length && <span className="cc-h">Nothing matches</span>}
              {extra && (
                <>
                  <span className="cc-sep" />
                  {extra(close)}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
