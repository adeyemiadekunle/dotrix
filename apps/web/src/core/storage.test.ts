import { describe, expect, it } from "vitest";

import { formatBytes, storageLine } from "./storage";

describe("storageLine", () => {
  it("reads used of limit", () => {
    const l = storageLine(312_000_000, 1_000_000_000);
    expect(l.text).toBe("Storage: 312 MB of 1 GB used");
    expect(l.tone).toBe("ok");
    expect(l.ratio).toBeCloseTo(0.312);
    expect(l.note).toBeNull();
  });

  it("warns from 80% and is full at the limit", () => {
    expect(storageLine(799_999_999, 1_000_000_000).tone).toBe("ok");
    expect(storageLine(800_000_000, 1_000_000_000).tone).toBe("warn");
    const full = storageLine(1_200_000_000, 1_000_000_000);
    expect(full.tone).toBe("full");
    expect(full.ratio).toBe(1);
    expect(full.note).toBe("Uploads are paused until you delete files or the limit is raised.");
  });

  it("shows only what is used without a limit", () => {
    expect(storageLine(5_500_000_000, null)).toEqual({ text: "Storage: 5.5 GB used", ratio: null, tone: "ok", note: null });
  });

  it("formats small sizes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(2_500)).toBe("3 KB");
  });
});
