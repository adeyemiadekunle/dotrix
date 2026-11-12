import { describe, expect, it } from "vitest";

import { reduce, retryDelay } from "@/lib/runStream";

const empty = (key: string) => ({ key, text: "", thinking: "", activity: null });

describe("run stream state", () => {
  it("never carries one run's text into the next", () => {
    const a = reduce(empty("a"), "a", "text", "old reply");
    expect(a.text).toBe("old reply");
    const b = reduce(a, "b", "activity", "Reading");
    expect(b).toEqual({ key: "b", text: "", thinking: "", activity: "Reading" });
  });

  it("starts over when a late event from another run arrives", () => {
    const b = empty("b");
    // A late event for A is reduced under A's key onto B's state: it starts A's own state and B's text is not appended to.
    const late = reduce(b, "a", "delta", "late");
    expect(late.key).toBe("a");
    expect(late.text).toBe("late");
  });

  it("replaces text and clears thinking on text, appends on delta", () => {
    let s = reduce(empty("a"), "a", "thinking", "hm");
    s = reduce(s, "a", "thinking", "m");
    expect(s.thinking).toBe("hmm");
    s = reduce(s, "a", "text", "Hello");
    expect(s).toMatchObject({ text: "Hello", thinking: "" });
    s = reduce(s, "a", "delta", " world");
    expect(s.text).toBe("Hello world");
    s = reduce(s, "a", "thinking_text", "so far");
    expect(s.thinking).toBe("so far");
  });

  it("clears the activity at the end", () => {
    const s = reduce(reduce(empty("a"), "a", "activity", "Reading"), "a", "end");
    expect(s.activity).toBeNull();
  });

  it("waits longer after each failure, to 15 seconds", () => {
    expect([0, 1, 2, 3, 4, 5, 10].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 15000, 15000, 15000]);
  });
});
