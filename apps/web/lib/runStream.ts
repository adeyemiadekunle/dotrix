// One server-sent-events stream of an agent's reply as it's written, shared by a project's runs and conversations across projects.
import { useEffect, useRef, useState } from "react";

import { ensureSession } from "@/lib/api";

/** The reply as it's being written. */
export interface StreamedReply {
  /** The reply so far. */
  text: string;
  /** What the agent is doing right now ("Reading roadmap.md"), or null. */
  activity: string | null;
  /** What it has thought so far, as its model summarises it (empty when it shows none). */
  thinking: string;
}

export type StreamEvent = "text" | "delta" | "activity" | "thinking_text" | "thinking" | "end";

interface Held extends StreamedReply {
  /** The run this state belongs to: state for another run is never shown. */
  key: string;
}

const EMPTY: StreamedReply = { text: "", thinking: "", activity: null };

/** The state for `key` after an event: state held for any other run starts over from empty. */
export function reduce(state: Held, key: string, event: StreamEvent, data = ""): Held {
  const base: Held = state.key === key ? state : { key, ...EMPTY };
  switch (event) {
    case "text":
      return { ...base, text: data, thinking: "" };
    case "delta":
      return { ...base, text: base.text + data };
    case "activity":
      return { ...base, activity: data };
    case "thinking_text":
      return { ...base, thinking: data };
    case "thinking":
      return { ...base, thinking: base.thinking + data };
    case "end":
      return { ...base, activity: null };
  }
}

/** The delay before reconnecting after the nth failure in a row: doubling from a second, to 15 seconds at most. */
export const retryDelay = (failures: number) => Math.min(1000 * 2 ** failures, 15_000);

/**
 * Follows a run's stream while `active` and `url` is set. A dropped connection reconnects (the server
 * sends the text so far again), a little later each time. State is kept with the run's `key`, so a
 * new run starts empty and a late event from an old stream changes nothing.
 */
export function useEventStream({ url, key, active, onEnd }: { url: string | undefined; key: string; active: boolean; onEnd?: () => void }): StreamedReply {
  const [state, setState] = useState<Held>({ key, ...EMPTY });
  const [attempt, setAttempt] = useState(0);
  const failures = useRef(0);
  const ended = useRef(onEnd);
  ended.current = onEnd;
  useEffect(() => {
    failures.current = 0;
  }, [key]);
  useEffect(() => {
    if (!url || !active) return;
    let source: EventSource | undefined;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    // An EventSource can't refresh an expired session itself: check it's current first.
    void ensureSession().then(() => {
      if (closed) return;
      source = new EventSource(url);
      const stream = source;
      const read = (event: Event) => (JSON.parse((event as MessageEvent).data) as { text: string }).text;
      // Each connection (and each new step) starts with the text so far, then the thinking so far.
      for (const name of ["text", "delta", "activity", "thinking_text", "thinking"] as const) {
        stream.addEventListener(name, (e) => {
          if (closed) return;
          const data = read(e);
          setState((s) => reduce(s, key, name, data));
        });
      }
      // The stream ends when the run does (or wasn't running): don't let EventSource reconnect,
      // and fetch the finished run right away rather than at the next poll.
      stream.addEventListener("end", () => {
        stream.close();
        if (closed) return;
        setState((s) => reduce(s, key, "end"));
        ended.current?.();
      });
      stream.addEventListener("open", () => (failures.current = 0));
      stream.onerror = () => {
        stream.close();
        if (!closed) retry = setTimeout(() => setAttempt((a) => a + 1), retryDelay(failures.current++));
      };
    });
    return () => {
      closed = true;
      clearTimeout(retry);
      source?.close();
    };
  }, [url, key, active, attempt]);
  // Another run's state is never returned, not even for one render.
  const current = state.key === key ? state : { key, ...EMPTY };
  return { text: current.text, activity: current.activity, thinking: current.thinking };
}
