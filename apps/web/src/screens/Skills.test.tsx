// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";

import type { SkillRegistry } from "../data/account";
import { SkillsCatalog, agentDisplayName, filterSkills } from "./Skills";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const mounted: ReturnType<typeof createRoot>[] = [];
afterEach(() => {
  mounted.forEach((root) => act(() => root.unmount()));
  mounted.length = 0;
  document.body.replaceChildren();
});

const REGISTRY: SkillRegistry = {
  categories: [
    { id: "frontend", label: "Frontend" },
    { id: "browser", label: "Browser & Automation" },
    { id: "product", label: "Product & UX" },
  ],
  items: [
    {
      id: "frontend-modern-web-guidance",
      name: "Modern Web Guidance",
      description: "Core Web Vitals and accessible HTML/CSS guidance.",
      category: "frontend",
      tags: ["web", "accessibility"],
      agents: ["coding", "architecture", "reviewer"],
      required_tools: [],
      trust: "reviewed",
      origin: "bundle",
      enabled: false,
      version: 0,
      registry_version: "1.0.0",
      sha256: "abcdef1234567890" + "0".repeat(48),
      source_repo: "https://github.com/GoogleChrome/modern-web-guidance-src",
      source_revision: "curated-2026-11-22",
      license: "Apache-2.0",
      content: "# Skill: Modern Web Guidance\n",
      updated_at: null,
    },
    {
      id: "browser-exploratory-verification",
      name: "Browser Exploratory Verification",
      description: "Inspect live local UIs with sandboxed browser actions.",
      category: "browser",
      tags: ["browser", "qa"],
      agents: ["coding"],
      required_tools: ["browser"],
      trust: "reviewed",
      origin: "bundle",
      enabled: true,
      version: 2,
      registry_version: "1.0.0",
      sha256: "123456abcdef7890" + "0".repeat(48),
      source_repo: "https://agent-browser.dev/introduction",
      source_revision: "curated-2026-11-22",
      license: "Apache-2.0",
      content: "# Skill: Browser Exploratory Verification\n",
      updated_at: null,
    },
    {
      id: "team-check",
      name: "Team Check",
      description: "Internal workspace checklist.",
      category: "product",
      tags: ["internal"],
      agents: ["product", "project-manager"],
      required_tools: [],
      trust: "workspace",
      origin: "workspace",
      enabled: true,
      version: 1,
      registry_version: "1.0.0",
      sha256: "9999999999990000" + "0".repeat(48),
      source_repo: null,
      source_revision: null,
      license: null,
      content: "Description: Internal workspace checklist.\n",
      updated_at: null,
    },
  ],
};

it("maps agent handles to Dotrix names and filters by category, origin, and search text", () => {
  expect(agentDisplayName("coding")).toBe("Kai");
  expect(agentDisplayName("architecture")).toBe("Orion");
  expect(agentDisplayName("reviewer")).toBe("Juno");
  expect(agentDisplayName("product")).toBe("Lyra");
  expect(agentDisplayName("project-manager")).toBe("Nova");

  expect(filterSkills(REGISTRY.items, "", "frontend", "all").map((s) => s.id)).toEqual(["frontend-modern-web-guidance"]);
  expect(filterSkills(REGISTRY.items, "", "all", "workspace").map((s) => s.id)).toEqual(["team-check"]);
  expect(filterSkills(REGISTRY.items, "Nova", "all", "all").map((s) => s.id)).toEqual(["team-check"]);
  expect(filterSkills(REGISTRY.items, "juno", "all", "all").map((s) => s.id)).toEqual(["frontend-modern-web-guidance"]);
});

it("renders categories, provenance, trust badges, and agent names", () => {
  const html = renderToStaticMarkup(<SkillsCatalog data={REGISTRY} canManage onSave={async () => {}} />);
  expect(html).toContain("Frontend (1)");
  expect(html).toContain("Browser &amp; Automation (1)");
  expect(html).toContain("Modern Web Guidance");
  expect(html).toContain("Reviewed");
  expect(html).toContain("Kai, Orion, Juno");
  expect(html).toContain("Required tools: browser");
  expect(html).toContain("sha256:abcdef123456");
  expect(html).toContain("curated-2026-11-22");
  expect(html).toContain("Apache-2.0");
  expect(html).toContain("https://github.com/GoogleChrome/modern-web-guidance-src");
});

it("filters by category click and calls onSave when enabling a reviewed bundle", async () => {
  const onSave = vi.fn(async () => {});
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mounted.push(root);

  act(() => {
    root.render(<SkillsCatalog data={REGISTRY} canManage onSave={onSave} />);
  });

  const buttons = [...container.querySelectorAll("button")];
  const frontendBtn = buttons.find((b) => b.textContent?.includes("Frontend (1)"))!;
  act(() => frontendBtn.click());
  expect(container.textContent).toContain("Modern Web Guidance");
  expect(container.textContent).not.toContain("Team Check");

  const enableBtn = [...container.querySelectorAll("button")].find((b) => b.textContent?.trim() === "Enable")!;
  await act(async () => {
    enableBtn.click();
  });
  expect(onSave).toHaveBeenCalledWith("frontend-modern-web-guidance", "# Skill: Modern Web Guidance\n", 0);
});
