import { ActionButton } from "@dotrix/ui/components/action-button";
import { Popover, PopoverPopup, PopoverTrigger } from "@dotrix/ui/components/chat/ui/popover";
import { Input } from "@dotrix/ui/components/input";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { Ic } from "../core/icons";

export type SessionTab = {
  id: string;
  title: string;
  onSelect: () => void;
  waiting?: boolean;
};

export function SessionTabs({
  area,
  activeId,
  tabs,
  onNew,
  copyLink,
  query,
  setQuery,
  children,
}: {
  area: "chat" | "code";
  activeId: string | null;
  tabs: SessionTab[];
  onNew: () => void;
  copyLink: () => void;
  query: string;
  setQuery: (next: string) => void;
  children: (close: () => void) => ReactNode;
}) {
  const chat = area === "chat";
  const name = chat ? "Chat" : "Code";
  const newLabel = chat ? "New chat" : "New session";
  const browse = chat ? "Browse conversations" : "Browse sessions";
  const find = chat ? "Find a conversation" : "Find a session";
  const [open, setOpen] = useState(false);
  const strip = useRef<HTMLDivElement>(null);
  const current = tabs.find((tab) => tab.id === activeId);
  const recent = tabs.slice(0, current || !activeId ? 5 : 4);
  // A link to an older session always gets its own tab.
  if (current && !recent.includes(current)) recent.splice(4, 1, current);
  const tabOrder = recent.map((tab) => tab.id).join("|");

  useLayoutEffect(() => {
    const bar = strip.current;
    const active = bar?.querySelector<HTMLElement>("[aria-current]");
    if (!bar || !active) return;
    const align = () => {
      const viewport = bar.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      if (item.left < viewport.left) bar.scrollLeft -= viewport.left - item.left;
      else if (item.right > viewport.right) bar.scrollLeft += item.right - viewport.right;
    };
    align();
    const observer = new ResizeObserver(align);
    observer.observe(bar);
    observer.observe(active);
    return () => observer.disconnect();
  }, [activeId, current?.title, tabOrder]);

  return (
    <div className="session-tab-bar">
      <h1 className="sr-only">{name}</h1>
      <div ref={strip} className="session-tab-strip" role="navigation" aria-label={chat ? "Chat tabs" : "Code tabs"}>
        {(!activeId || !current) && (
          <span className="session-tab draft" aria-current="page">
            <Ic n={chat ? "message-square" : "code"} s={14} />
            {activeId ? (chat ? "Conversation" : "Session") : newLabel}
          </span>
        )}
        {recent.map((tab) => (
          <ActionButton
            key={tab.id}
            className="session-tab"
            aria-current={tab.id === activeId ? "page" : undefined}
            title={tab.title}
            onClick={tab.id === activeId ? undefined : tab.onSelect}
          >
            <Ic n={chat ? "message-square" : "code"} s={14} />
            <span className="trunc">{tab.title}</span>
            {tab.waiting && <span className="sdot" aria-label="Waiting for a decision" />}
          </ActionButton>
        ))}
      </div>
      <div className="session-tab-actions">
        <ActionButton className="ibtn ibtn-sm" onClick={onNew} aria-label={newLabel} title={newLabel}>
          <Ic n="plus" s={17} />
        </ActionButton>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger render={<ActionButton className="ibtn ibtn-sm" />} aria-label={browse} title={browse}>
            <Ic n="chevron-down" s={17} />
          </PopoverTrigger>
          <PopoverPopup className="session-tab-popup" align="end" sideOffset={8} collisionPadding={12} aria-label={browse}>
            <Input className="input search-sm" placeholder={find} aria-label={find} value={query} onChange={(event) => setQuery(event.target.value)} />
            {children(() => setOpen(false))}
            {activeId && (
              <ActionButton
                className="btn btn-ghost btn-sm session-tab-copy"
                onClick={() => {
                  copyLink();
                  setOpen(false);
                }}
              >
                <Ic n="link" s={14} />
                {chat ? "Copy conversation link" : "Copy session link"}
              </ActionButton>
            )}
          </PopoverPopup>
        </Popover>
      </div>
    </div>
  );
}
