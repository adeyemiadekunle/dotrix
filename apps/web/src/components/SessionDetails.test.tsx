import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import type { CodingRun, CodingSession } from "@/lib/coding";
import { SessionDetails } from "./SessionDetails";

const useCodingEventsMock = vi.fn(() => ({
  data: undefined as CodingRun["events"] | undefined,
  isLoading: false,
  isFetching: false,
  isError: false,
  refetch: vi.fn(),
}));

vi.mock("@/lib/agent", () => ({ modelName: (name: string) => name }));
vi.mock("@/lib/coding", () => ({
  useCodingEvents: () => useCodingEventsMock(),
  statusLabel: (run: { status: string }) => run.status,
}));

it("shows pinned skill versions, resources, and unavailable tool requirements", () => {
  useCodingEventsMock.mockReturnValueOnce({ data: undefined, isLoading: false, isFetching: false, isError: false, refetch: vi.fn() });
  const run = {
    id: "run",
    files_changed: [],
    capabilities: [
      { id: "repository.read", label: "Read repository", available: true },
      { id: "browser", label: "Browser", available: false, reason: "Not offered in Plan mode" },
    ],
    skills: [
      {
        name: "team-check",
        description: "Team procedure",
        sha256: "a".repeat(64),
        resources: ["references/checklist.md"],
        missing_resources: ["templates/report.md"],
        unavailable_tools: ["browser"],
      },
    ],
  } as unknown as CodingRun;
  const html = renderToStaticMarkup(
    <SessionDetails
      cs={{ project_name: "Test", location: "cloud" } as CodingSession}
      turns={[run]}
      onOpenFile={() => {}}
      onOpenChanges={() => {}}
      onShot={() => {}}
      shotSrc={() => ""}
    />,
  );
  expect(html).toContain("Tools and skills");
  expect(html).toContain("Read repository");
  expect(html).toContain("Not offered in Plan mode");
  expect(html).toContain("aaaaaaaaaaaa");
  expect(html).toContain("references/checklist.md");
  expect(html).toContain("templates/report.md");
  expect(html).toContain("Unavailable required tools: browser");
  expect(html).not.toContain("Full private procedure");
});

it("shows Background tasks section when empty and when populated from run tasks or coding events API", () => {
  useCodingEventsMock.mockReturnValueOnce({ data: undefined, isLoading: false, isFetching: false, isError: false, refetch: vi.fn() });
  const emptyHtml = renderToStaticMarkup(
    <SessionDetails
      cs={{ project_name: "Test", location: "cloud", status: "changes_ready" } as CodingSession}
      turns={[{ id: "run-empty", status: "changes_ready", files_changed: [], events: [] } as unknown as CodingRun]}
      onOpenFile={() => {}}
      onOpenChanges={() => {}}
      onShot={() => {}}
      shotSrc={() => ""}
    />,
  );
  expect(emptyHtml).toContain("Background tasks");
  expect(emptyHtml).toContain("No background tasks in this session.");

  useCodingEventsMock.mockReturnValueOnce({
    data: [{ kind: "background-done", ref: "command:c1", text: "pnpm test", at: "2026-11-24T08:00:00Z" }],
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  });
  const liveHtml = renderToStaticMarkup(
    <SessionDetails
      scope={{ workspaceId: "ws1", projectId: "p1" }}
      cs={{ project_name: "Test", location: "cloud", status: "running" } as CodingSession}
      turns={[
        {
          id: "run-live",
          status: "running",
          files_changed: [],
          events: [],
          tasks: [{ key: "worker-api", status: "running", attempt: 1, owned_paths: ["src/api.ts"] }],
        } as unknown as CodingRun,
      ]}
      onOpenFile={() => {}}
      onOpenChanges={() => {}}
      onShot={() => {}}
      shotSrc={() => ""}
    />,
  );
  expect(liveHtml).toContain("Background tasks");
  expect(liveHtml).toContain("worker-api");
  expect(liveHtml).toContain("Working · 1 paths");
  expect(liveHtml).toContain("pnpm test");
  expect(liveHtml).toContain("Command · Done");
});
