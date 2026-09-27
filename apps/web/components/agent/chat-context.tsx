"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

interface ChatState {
  /** The side panel is open (desktop) or the sheet is showing (phones). */
  open: boolean;
  setOpen: (open: boolean) => void;
  /** The conversation being shown; null starts a new one with the next message. */
  threadId: string | null;
  setThreadId: (threadId: string | null) => void;
  /** Show a conversation (e.g. one a button just started) and open the panel. */
  show: (threadId: string) => void;
}

const ChatContext = createContext<ChatState | null>(null);

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Remembering the panel is a convenience; blocked storage just means it starts fresh.
  }
}

/** Chat state for one project: which conversation is open, and whether the panel is. */
export function ChatProvider({ projectId, children }: { projectId: string | undefined; children: ReactNode }) {
  const [open, setOpenState] = useState(false);
  const [threadId, setThreadState] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setThreadState(read(`pmagent.thread.${projectId}`));
    // Reopen the panel beside the page on wide screens; on phones it's a sheet over the page,
    // which should only appear when asked for.
    setOpenState(read("pmagent.chatOpen") === "1" && window.matchMedia("(min-width: 768px)").matches);
  }, [projectId]);

  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    write("pmagent.chatOpen", next ? "1" : null);
  }, []);
  const setThreadId = useCallback(
    (next: string | null) => {
      setThreadState(next);
      if (projectId) write(`pmagent.thread.${projectId}`, next);
    },
    [projectId],
  );
  const show = useCallback(
    (next: string) => {
      setThreadId(next);
      setOpen(true);
    },
    [setOpen, setThreadId],
  );

  return <ChatContext value={{ open, setOpen, threadId, setThreadId, show }}>{children}</ChatContext>;
}

export function useChat(): ChatState {
  const chat = useContext(ChatContext);
  if (!chat) throw new Error("useChat needs a ChatProvider");
  return chat;
}
