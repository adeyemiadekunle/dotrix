// How Kai reads a page (node --test, after tsc).
import assert from "node:assert/strict";
import { test } from "node:test";

import { renderTree, type AxNode } from "./browserTree";

const node = (nodeId: string, role: string, name: string, more: Partial<AxNode> = {}): AxNode => ({
  nodeId,
  role: { value: role },
  name: { value: name },
  ...more,
});

test("a page reads as a tree, with refs on what can be acted on", () => {
  const tree = renderTree([
    node("1", "RootWebArea", "Sign in", { childIds: ["2", "5", "6", "8"] }),
    node("2", "heading", "Welcome  back", { parentId: "1", childIds: ["3"], backendDOMNodeId: 10 }),
    node("3", "StaticText", "Welcome back", { parentId: "2", childIds: ["4"] }),
    node("4", "InlineTextBox", "Welcome back", { parentId: "3" }),
    node("5", "generic", "", { parentId: "1", childIds: ["7"] }),
    node("7", "textbox", "Email", {
      parentId: "5",
      childIds: ["10"],
      backendDOMNodeId: 12,
      value: { value: "a@b.c" },
      properties: [{ name: "required", value: { value: true } }],
    }),
    node("10", "StaticText", "a@b.c", { parentId: "7" }),
    node("6", "button", "Sign in", { parentId: "1", backendDOMNodeId: 13, properties: [{ name: "disabled", value: { value: true } }] }),
    node("8", "paragraph", "", { parentId: "1", ignored: true, childIds: ["9"] }),
    node("9", "StaticText", "Forgot it?", { parentId: "8" }),
  ]);
  assert.equal(
    tree,
    [
      '- RootWebArea "Sign in"',
      '  - heading "Welcome back"',
      '  - textbox "Email" value="a@b.c" [required] [ref=12]',
      '  - button "Sign in" [disabled] [ref=13]',
      '  - text "Forgot it?"',
    ].join("\n"),
  );
});

test("a long page is cut", () => {
  const nodes = [node("0", "RootWebArea", "Long", { childIds: Array.from({ length: 200 }, (_, i) => String(i + 1)) })];
  for (let i = 1; i <= 200; i++) nodes.push(node(String(i), "link", `Link number ${i}`, { parentId: "0", backendDOMNodeId: i }));
  const tree = renderTree(nodes, 500);
  assert.ok(tree.length < 600);
  assert.ok(tree.endsWith("… (the rest of the page is cut)"));
});
