import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import type { CodingRun, CodingSession } from "@/lib/coding";
import { SessionDetails } from "./SessionDetails";

vi.mock("@/lib/agent", () => ({ modelName: (name: string) => name }));

it("shows pinned skill versions, resources, and unavailable tool requirements", () => {
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
