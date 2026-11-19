import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { issueQueriesOf } from "../../lib/issues";

describe("issueQueriesOf", () => {
  it("covers the project's and the workspace's issue queries, and no other workspace", () => {
    const client = new QueryClient();
    const lists = ["issues", "workspace", "w1", { archived: "include" }] as const;
    const project = ["issues", "p1", "all"] as const;
    const other = ["issues", "workspace", "w2", {}] as const;
    for (const key of [lists, project, other]) client.setQueryData(key, []);
    for (const queryKey of issueQueriesOf({ workspaceId: "w1", projectId: "p1" })) void client.invalidateQueries({ queryKey });
    expect(client.getQueryState(lists)?.isInvalidated).toBe(true);
    expect(client.getQueryState(project)?.isInvalidated).toBe(true);
    expect(client.getQueryState(other)?.isInvalidated).toBe(false);
  });
});
