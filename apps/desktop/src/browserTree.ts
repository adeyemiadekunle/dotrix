// A page as Kai reads it: Chromium's accessibility tree as indented text, each thing Kai can act on
// with a ref (its DOM node's id) for browser_click and browser_type. Pure, so node --test checks it.

/** A node of CDP's Accessibility.getFullAXTree (only what's read here). */
export interface AxNode {
  nodeId: string;
  ignored?: boolean;
  role?: { value?: unknown };
  name?: { value?: unknown };
  value?: { value?: unknown };
  properties?: { name: string; value?: { value?: unknown } }[];
  childIds?: string[];
  parentId?: string;
  backendDOMNodeId?: number;
}

const SKIPPED = new Set(["none", "generic", "InlineTextBox", "LineBreak", "presentation"]);
const ACTED_ON = new Set([
  "button",
  "link",
  "textbox",
  "searchbox",
  "combobox",
  "checkbox",
  "radio",
  "switch",
  "tab",
  "menuitem",
  "menuitemcheckbox",
  "menuitemradio",
  "option",
  "slider",
  "spinbutton",
  "listbox",
]);
const FLAGS = ["checked", "disabled", "expanded", "selected", "required", "invalid", "pressed"];

const text = (value: unknown, limit = 200): string => {
  const said = typeof value === "string" ? value.replace(/\s+/g, " ").trim() : typeof value === "number" ? String(value) : "";
  return said.length > limit ? `${said.slice(0, limit)}…` : said;
};

/** The page's tree as text, at most `limit` characters. */
export function renderTree(nodes: AxNode[], limit = 20_000): string {
  const byId = new Map(nodes.map((node) => [node.nodeId, node]));
  const root = nodes.find((node) => !node.parentId) ?? nodes[0];
  const lines: string[] = [];
  let size = 0;
  let cut = false;
  const walk = (node: AxNode | undefined, depth: number, parentSays: string[]): void => {
    if (!node || cut) return;
    const role = text(node.role?.value);
    const name = text(node.name?.value);
    const shown = !node.ignored && !(SKIPPED.has(role) && !name) && role !== "InlineTextBox";
    // Text that only repeats the name or value of what holds it says nothing new.
    const repeats = role === "StaticText" && (!name || parentSays.includes(name));
    if (shown && !repeats) {
      const props = new Map((node.properties ?? []).map((prop) => [prop.name, prop.value?.value]));
      const flags = FLAGS.filter((flag) => props.get(flag) === true || props.get(flag) === "true").map((flag) => ` [${flag}]`);
      const value = text(node.value?.value);
      const ref = node.backendDOMNodeId && (ACTED_ON.has(role) || props.get("focusable") === true) ? ` [ref=${node.backendDOMNodeId}]` : "";
      const line =
        role === "StaticText"
          ? `${"  ".repeat(depth)}- text "${name}"`
          : `${"  ".repeat(depth)}- ${role || "node"}${name ? ` "${name}"` : ""}${value && value !== name ? ` value="${value}"` : ""}${flags.join("")}${ref}`;
      size += line.length + 1;
      if (size > limit) {
        cut = true;
        lines.push("… (the rest of the page is cut)");
        return;
      }
      lines.push(line);
    }
    const next = shown && !repeats ? depth + 1 : depth;
    for (const id of node.childIds ?? []) walk(byId.get(id), next, shown ? [name, text(node.value?.value)] : parentSays);
  };
  walk(root, 0, []);
  return lines.join("\n");
}
