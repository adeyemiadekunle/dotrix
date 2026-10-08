// Gr8r's toasts (gr8r-studio/src/ui/toast.js): a message, an optional action (Undo), dismissable.
import { useSyncExternalStore } from "react";

import { Ic } from "../core/icons";

interface Toast {
  id: number;
  msg: string;
  kind?: "err" | "info";
  action?: string;
  onAction?: () => void;
  out?: boolean;
}

let toasts: Toast[] = [];
let n = 0;
const listeners = new Set<() => void>();
const emit = () => {
  toasts = [...toasts];
  for (const l of listeners) l();
};

export function toast(msg: string, opt: { kind?: "err" | "info"; action?: string; onAction?: () => void; ms?: number } = {}) {
  const t: Toast = { id: ++n, msg, kind: opt.kind, action: opt.action, onAction: opt.onAction };
  toasts.push(t);
  emit();
  setTimeout(() => kill(t.id), opt.ms ?? 4200);
}
function kill(id: number) {
  const t = toasts.find((x) => x.id === id);
  if (!t || t.out) return;
  t.out = true;
  emit();
  setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== id);
    emit();
  }, 160);
}

export function Toasts() {
  const list = useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => toasts,
  );
  return (
    <div id="toasts" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className={`toast ${t.out ? "out" : ""}`} role="status">
          {t.kind === "err" ? <Ic n="circle-alert" s={15} cls="bad" /> : t.kind === "info" ? <Ic n="info" s={15} /> : <Ic n="circle-check" s={15} cls="ok" />}
          <span className="grow">{t.msg}</span>
          {t.action && (
            <button
              className="ta"
              onClick={() => {
                t.onAction?.();
                kill(t.id);
              }}
            >
              {t.action}
            </button>
          )}
          <button className="ibtn ibtn-xs" aria-label="Dismiss" style={{ color: "inherit", opacity: 0.6 }} onClick={() => kill(t.id)}>
            <Ic n="x" s={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
