import { useEffect } from "react";
import { Button } from "@astryxdesign/core/Button";
import { useToast, type ToastOptions } from "@astryxdesign/core/Toast";

type Listener = (options: ToastOptions) => void;
const listeners = new Set<Listener>();
const pending: ToastOptions[] = [];
function show(body: string, options: Partial<ToastOptions> = {}) {
  const notification = { body, isAutoHide: true, autoHideDuration: 4200, ...options };
  if (!listeners.size) pending.push(notification);
  else listeners.forEach((listener) => listener(notification));
}
export const toast = Object.assign(show, {
  success: (body: string) => show(body),
  error: (body: string) => show(body, { type: "error" }),
  info: (body: string) => show(body),
});
export function ToastHost() {
  const notify = useToast();
  useEffect(() => {
    const listener: Listener = (options) => {
      notify(options);
    };
    listeners.add(listener);
    pending.splice(0).forEach(listener);
    return () => {
      listeners.delete(listener);
    };
  }, [notify]);
  return null;
}
/** Preserves Dotrix's imperative toast and Undo contract. */
export function notify(message: string, options: { kind?: "err" | "info"; action?: string; onAction?: () => void; ms?: number } = {}) {
  show(message, {
    type: options.kind === "err" ? "error" : "info",
    autoHideDuration: options.ms ?? 4200,
    renderContent: ({ body, dismiss }) => (
      <div className="row" style={{ gap: 12 }}>
        <span className="grow">{body}</span>
        {options.action && (
          <Button
            label={options.action}
            size="sm"
            variant="ghost"
            onClick={() => {
              options.onAction?.();
              dismiss();
            }}
          />
        )}
        <Button label="Dismiss notification" isIconOnly icon={<span aria-hidden>×</span>} size="sm" variant="ghost" onClick={dismiss} />
      </div>
    ),
  });
}
