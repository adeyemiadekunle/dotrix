// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { CodingRun } from "@/lib/coding";
import { BackgroundTasks } from "./BackgroundTasks";

vi.mock("@/lib/coding", () => ({ useCodingEvents: () => ({ data: undefined, isLoading: false, isError: false }) }));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const mounted: ReturnType<typeof createRoot>[] = [];
afterEach(() => {
  mounted.forEach((root) => act(() => root.unmount()));
  mounted.length = 0;
  document.body.replaceChildren();
});

it("expands saved worker history with its command, output and checks", () => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mounted.push(root);
  const run = {
    id: "run",
    turn: 2,
    status: "no_changes",
    event_count: 2,
    tasks: [{ key: "api", status: "completed", owned_paths: ["src/api/"], checks: [{ command: "pytest", exit_code: 0, output: "3 passed" }] }],
    events: [
      { kind: "tool", text: "[api] Ran pytest", ref: "api:1" },
      { kind: "output", text: "[api] 3 passed", ref: "api:1" },
    ],
  } as unknown as CodingRun;
  act(() => root.render(<BackgroundTasks scope={undefined} run={run} />));
  const heading = container.querySelector<HTMLButtonElement>("button")!;
  expect(heading.getAttribute("aria-expanded")).toBe("false");
  act(() => heading.click());
  const task = container.querySelector<HTMLButtonElement>(".background-task-heading")!;
  expect(task.textContent).toContain("Completed");
  act(() => task.click());
  expect(task.getAttribute("aria-expanded")).toBe("true");
  expect(container.textContent).toContain("src/api/");
  expect(container.textContent).toContain("pytest");
  expect(container.textContent).toContain("3 passed");
  expect(container.textContent).toContain("Passed");
  act(() => heading.click());
  expect(container.querySelector(".background-task-body")).toBeNull();
});
