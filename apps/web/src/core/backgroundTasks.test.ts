import { describe, expect, it } from "vitest";
import { taskEvents, taskStatus } from "./backgroundTasks";
import { terminal } from "./kaiWork";

describe("background task activity", () => {
  it("isolates interleaved tasks and keeps command/output references paired", () => {
    const at = "2026-11-12T12:00:00Z";
    const events = [
      { kind: "tool", text: "[api] Ran pytest", ref: "api:1", at },
      { kind: "tool", text: "[api-tests] Ran npm test", ref: "api-tests:1", at },
      { kind: "output", text: "[api] 3 passed", ref: "api:1", at },
      { kind: "step", text: "Task api: completed", at },
      { kind: "output-error", text: "[api-tests] test failed", ref: "api-tests:1", at },
    ];
    expect(terminal(taskEvents(events, "api"))).toEqual([{ ref: "api:1", command: "pytest", output: "3 passed", failed: false, at }]);
    expect(terminal(taskEvents(events, "api-tests"))[0].failed).toBe(true);
    expect(taskEvents(events, "missing")).toEqual([]);
  });

  it("does not label unfinished tasks as still running after the parent ends", () => {
    expect(taskStatus("running", "stopped")).toBe("Stopped");
    expect(taskStatus("queued", "failed")).toBe("Interrupted");
    expect(taskStatus("completed", "stopped")).toBe("Completed");
    expect(taskStatus("verifying", "running")).toBe("Checking");
  });
});
