// @vitest-environment jsdom
import { ActionButton } from "@dotrix/ui/components/action-button";
import { Button } from "@dotrix/ui/components/button";
import { Checkbox } from "@dotrix/ui/components/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@dotrix/ui/components/collapsible";
import { Input } from "@dotrix/ui/components/input";
import { SelectField } from "@dotrix/ui/components/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@dotrix/ui/components/tabs";
import { Textarea } from "@dotrix/ui/components/textarea";
import { createAgent, registerTools } from "@ui-sdk/react/agent";
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

declare global {
  var __UI_SDK_STRICT__: boolean | undefined;
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined;
}

let approveConfirm = false;
const agent = createAgent({
  allow: (step) => !step.confirm || approveConfirm,
});

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeAll(() => {
  globalThis.__UI_SDK_STRICT__ = true;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;

  HTMLElement.prototype.showPopover = function () {};
  HTMLElement.prototype.hidePopover = function () {};
  Element.prototype.getAnimations = () => [];
  Element.prototype.scrollIntoView = function () {};
  Element.prototype.checkVisibility = () => true;
  Element.prototype.getClientRects = () => [] as unknown as DOMRectList;
  document.elementFromPoint = () => null;
  document.elementsFromPoint = () => [];
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  document.head.append(
    Object.assign(document.createElement("style"), {
      textContent: "[popover] { display: block !important }",
    }),
  );
});

afterEach(async () => {
  approveConfirm = false;
  if (root) {
    const activeRoot = root;
    root = null;
    await act(async () => {
      activeRoot.unmount();
    });
  }
  container?.remove();
  container = null;
});

async function renderNode(node: React.ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root!.render(node);
  });
  return container;
}

function SampleSettings({ onSave, onDelete, onRunAction = () => {} }: { onSave: () => void; onDelete: () => void; onRunAction?: () => void }) {
  const [name, setName] = useState("Apollo");
  const [notes, setNotes] = useState("");
  const [alerts, setAlerts] = useState(false);
  const [region, setRegion] = useState("us");
  const [tab, setTab] = useState("general");

  return (
    <div>
      <Input aria-label="Project name" value={name} onChange={(e) => setName(e.target.value)} />
      <Textarea aria-label="Project notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <Checkbox aria-label="Enable alerts" checked={alerts} onCheckedChange={(next) => setAlerts(next === true)} />
      <SelectField
        aria-label="Deployment region"
        value={region}
        onValueChange={setRegion}
        options={[
          { value: "us", label: "United States" },
          { value: "eu", label: "Europe" },
        ]}
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Settings section">
          <TabsTrigger value="general">General</TabsTrigger>
          <TabsTrigger value="advanced">Advanced</TabsTrigger>
        </TabsList>
        <TabsContent value="general">General panel</TabsContent>
        <TabsContent value="advanced">Advanced panel</TabsContent>
      </Tabs>
      <Collapsible>
        <CollapsibleTrigger>More details</CollapsibleTrigger>
        <CollapsibleContent>Extra details body</CollapsibleContent>
      </Collapsible>
      <ActionButton onClick={onRunAction}>Run action</ActionButton>
      <Button asChild>
        <a href="#docs">Read docs</a>
      </Button>
      <Button onClick={onSave}>Save changes</Button>
      <Button data-agent-confirm="Deletes the item" onClick={onDelete}>
        Delete item
      </Button>
    </div>
  );
}

describe("uiAgent inspection bridge", () => {
  it("snapshots all migrated controls and runs agent.act steps", async () => {
    const onSave = vi.fn();
    const onRunAction = vi.fn();
    const dom = await renderNode(<SampleSettings onSave={onSave} onDelete={() => {}} onRunAction={onRunAction} />);

    const components = agent.snapshot().filter((entry) => !entry.offPage && entry.component !== "more");
    for (const entry of components) {
      expect(entry.label, `${entry.component} ${entry.ref} has no name`).toBeTruthy();
    }

    const labels = components.map((entry) => entry.label);
    for (const label of [
      "Project name",
      "Project notes",
      "Enable alerts",
      "Deployment region",
      "Settings section",
      "More details",
      "Run action",
      "Read docs",
      "Save changes",
      "Delete item",
    ]) {
      expect(labels, `${label} is missing from snapshot`).toContain(label);
    }

    const docsLink = dom.querySelector('a[href="#docs"]');
    expect(docsLink?.textContent).toBe("Read docs");
    expect(dom.textContent).not.toContain("Extra details body");

    const result = await act(async () =>
      agent.act({
        steps: [
          { ref: "Project name", action: "setValue", args: ["Atlas"] },
          { ref: "Project notes", action: "setValue", args: ["Ready for release"] },
          { ref: "Enable alerts", action: "setChecked", args: [true] },
          { ref: "Deployment region", action: "setValue", args: ["eu"] },
          { ref: "Settings section", action: "setValue", args: ["advanced"] },
          { ref: "More details", action: "toggle" },
          { ref: "Run action", action: "press" },
          { ref: "Save changes", action: "press" },
        ],
      }),
    );

    expect(result.ok, result.error?.message).toBe(true);
    expect((dom.querySelector('input[aria-label="Project name"]') as HTMLInputElement).value).toBe("Atlas");
    expect((dom.querySelector('textarea[aria-label="Project notes"]') as HTMLTextAreaElement).value).toBe("Ready for release");
    expect(dom.querySelector('[aria-label="Enable alerts"]')?.getAttribute("aria-checked")).toBe("true");
    expect(dom.querySelector('[aria-label="Deployment region"]')?.getAttribute("data-value")).toBe("eu");
    expect(dom.textContent).toContain("Advanced panel");
    expect(dom.textContent).toContain("Extra details body");
    expect(onRunAction).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("gates data-agent-confirm buttons via allow callback", async () => {
    const onDelete = vi.fn();
    await renderNode(<SampleSettings onSave={() => {}} onDelete={onDelete} />);

    approveConfirm = false;
    const refused = await act(async () =>
      agent.act({
        steps: [{ ref: "Delete item", action: "press" }],
      }),
    );
    expect(refused.ok).toBe(false);
    expect(onDelete).not.toHaveBeenCalled();

    approveConfirm = true;
    const approved = await act(async () =>
      agent.act({
        steps: [{ ref: "Delete item", action: "press" }],
      }),
    );
    expect(approved.ok, approved.error?.message).toBe(true);
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("registers WebMCP tools with document.modelContext", async () => {
    await renderNode(<Input aria-label="Search query" defaultValue="dotrix" />);

    const tools = new Map<string, { execute: (input: object) => unknown }>();
    const previousContext = (document as { modelContext?: unknown }).modelContext;
    Object.assign(document, {
      modelContext: {
        registerTool: async (tool: { name: string; execute: (input: object) => unknown }) => {
          tools.set(tool.name, tool);
        },
      },
    });

    const unregister = registerTools(agent, { allow: () => true });
    try {
      const snapshotResult = await tools.get("snapshot")?.execute({});
      expect(Array.isArray(snapshotResult)).toBe(true);
      expect((snapshotResult as { label?: string }[]).some((entry) => entry.label === "Search query")).toBe(true);
    } finally {
      unregister();
      if (previousContext === undefined) {
        delete (document as { modelContext?: unknown }).modelContext;
      } else {
        Object.assign(document, { modelContext: previousContext });
      }
    }
  });
});
