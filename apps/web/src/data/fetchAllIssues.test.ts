import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAllIssues } from "../../lib/issues";

const rows = (from: number, n: number) => Array.from({ length: n }, (_, i) => ({ key: `r${from + i}` }));

/** A fake API over `total` rows, recording the offsets asked for. */
function pager(total: number, size: number) {
  const offsets: number[] = [];
  const fetchPage = async (offset: number) => {
    offsets.push(offset);
    return rows(offset, Math.max(0, Math.min(size, total - offset)));
  };
  return { offsets, fetchPage };
}

afterEach(() => vi.restoreAllMocks());

describe("fetchAllIssues", () => {
  it("makes one request for one short page", async () => {
    const p = pager(3, 10);
    expect(await fetchAllIssues(p.fetchPage, 10)).toHaveLength(3);
    expect(p.offsets).toEqual([0]);
  });

  it("asks again after a full page and stops at the empty one", async () => {
    const p = pager(10, 10);
    expect(await fetchAllIssues(p.fetchPage, 10)).toHaveLength(10);
    expect(p.offsets).toEqual([0, 10]);
  });

  it("keeps order across three pages", async () => {
    const p = pager(25, 10);
    const all = await fetchAllIssues(p.fetchPage, 10);
    expect(p.offsets).toEqual([0, 10, 20]);
    expect(all.map((r) => r.key)).toEqual(rows(0, 25).map((r) => r.key));
  });

  it("drops a row seen on two pages", async () => {
    const pages = [rows(0, 3), [...rows(2, 1), ...rows(3, 1)]];
    const all = await fetchAllIssues(async (o) => pages[o / 3] ?? [], 3);
    expect(all.map((r) => r.key)).toEqual(["r0", "r1", "r2", "r3"]);
  });

  it("stops after 50 pages and warns", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const p = { calls: 0 };
    const all = await fetchAllIssues(async (o) => {
      p.calls++;
      return rows(o, 2);
    }, 2);
    expect(p.calls).toBe(50);
    expect(all).toHaveLength(100);
    expect(warn).toHaveBeenCalledOnce();
  });
});
