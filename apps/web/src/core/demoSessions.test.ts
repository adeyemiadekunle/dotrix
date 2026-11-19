import { describe, expect, it } from "vitest";
import { seed } from "../data/seed";
import { demoCodingSessions } from "./demoSessions";
import { sessionHref } from "../../lib/coding";

describe("sample session parity", () => {
  it("preserves project, issue, status and history when adapting sample sessions", () => {
    const data = seed();
    const before = JSON.stringify(data);
    const rows = demoCodingSessions(data);
    expect(rows).toHaveLength(data.coding.length);
    for (const row of rows) {
      const source = data.coding.find((item) => item.id === row.session_id)!;
      expect(row.status).toBe(source.status);
      expect(row.turns).toBe(source.turns.length);
      expect(data.projects.some((project) => project.id === row.project_id)).toBe(true);
      expect(data.tasks.some((issue) => issue.key === row.issue_key)).toBe(true);
    }
    expect(JSON.stringify(data)).toBe(before);
  });
  it("omits orphaned sample sessions instead of attaching another project's data", () => {
    const data = seed();
    data.coding[0]!.project = "missing";
    expect(demoCodingSessions(data).some((item) => item.session_id === data.coding[0]!.id)).toBe(false);
  });
  it("opens shared session links directly in Codes", () => {
    expect(sessionHref("workspace", "ABC", "session-1")).toBe("/w/workspace/codes?project=ABC&session=session-1");
  });
});
