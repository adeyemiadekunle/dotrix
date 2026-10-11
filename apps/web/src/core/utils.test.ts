import { afterEach, describe, expect, it } from "vitest";

import { addD, ago, clamp, dayBucket, diffD, dOff, fmtDate, initials, iso, parse, relDate, setDateFormat, TODAY, WD } from "./utils";

describe("days", () => {
  it("round-trips ISO days in local time", () => {
    expect(iso(parse("2026-03-09")!)).toBe("2026-03-09");
    expect(parse("")).toBeNull();
    expect(parse(null)).toBeNull();
  });

  it("adds days across month and year ends", () => {
    expect(iso(addD(parse("2026-12-31")!, 1))).toBe("2027-01-01");
    expect(iso(addD(parse("2026-03-01")!, -1))).toBe("2026-02-28");
  });

  it("counts whole days whatever the time of day", () => {
    expect(diffD(new Date(2026, 0, 2, 0, 5), new Date(2026, 0, 1, 23, 55))).toBe(1);
    expect(diffD(new Date(2026, 0, 1, 8), new Date(2026, 0, 1, 20))).toBe(0);
  });
});

describe("fmtDate", () => {
  afterEach(() => setDateFormat(undefined));

  it("shows the year only when it isn't this year, or when asked", () => {
    expect(fmtDate("2020-03-09")).toBe("Mar 9, 2020");
    expect(fmtDate(dOff(0))).not.toContain(",");
    expect(fmtDate(dOff(0), true)).toContain(`, ${TODAY.getFullYear()}`);
  });

  it("follows the chosen format", () => {
    setDateFormat("d/M");
    expect(fmtDate("2020-03-09", true)).toBe("9/3/2020");
    setDateFormat("M/d");
    expect(fmtDate("2020-03-09")).toBe("3/9");
    setDateFormat("yyyy-MM-dd");
    expect(fmtDate("2020-03-09")).toBe("2020-03-09");
  });

  it("is empty without a date", () => {
    expect(fmtDate(null)).toBe("");
    expect(fmtDate("")).toBe("");
  });
});

describe("relative dates", () => {
  it("names the days around today", () => {
    expect(relDate(dOff(0))).toBe("Today");
    expect(relDate(dOff(1))).toBe("Tomorrow");
    expect(relDate(dOff(-1))).toBe("Yesterday");
    expect(relDate(dOff(3))).toBe(WD[parse(dOff(3))!.getDay()]);
    expect(relDate(null)).toBe("");
  });

  it("says how long ago, in the largest whole unit", () => {
    const now = Date.now();
    expect(ago(now - 20_000)).toBe("just now");
    expect(ago(now - 5 * 6e4)).toBe("5m ago");
    expect(ago(now - 3 * 36e5)).toBe("3h ago");
    expect(ago(now - 2 * 864e5)).toBe("2d ago");
  });

  it("groups times by day", () => {
    expect(dayBucket(Date.now())).toBe("Today");
    expect(dayBucket(addD(TODAY, -1).getTime() + 36e5)).toBe("Yesterday");
    expect(dayBucket(addD(TODAY, -3).getTime())).toBe("This week");
    expect(dayBucket(addD(TODAY, -30).getTime())).toBe("Earlier");
  });
});

describe("small helpers", () => {
  it("clamps to a range", () => {
    expect(clamp(5, 0, 3)).toBe(3);
    expect(clamp(-1, 0, 3)).toBe(0);
    expect(clamp(2, 0, 3)).toBe(2);
  });

  it("takes up to two initials", () => {
    expect(initials("Ada Lovelace")).toBe("AL");
    expect(initials("Ada King Lovelace")).toBe("AK");
    expect(initials("Cher")).toBe("C");
  });
});
