import type { KeyboardEvent } from "react";

/** Move and activate a tab with the keyboard, keeping the tab stop on the selected tab. */
export function tabKeys(e: KeyboardEvent<HTMLDivElement>) {
  const tabs = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)')];
  const current = tabs.indexOf(document.activeElement as HTMLButtonElement);
  if (current < 0 || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
  e.preventDefault();
  const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (current + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next]?.focus();
  tabs[next]?.click();
}
