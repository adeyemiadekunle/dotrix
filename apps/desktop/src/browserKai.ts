// Kai's hands on the Browser pane, for a turn coding on this computer: the tools the app's MCP server
// (mcp.ts) offers its coding tool. Kai has one tab of its own in the pane, which the person watches:
// the app's page makes it when Kai first asks (the pane opens for it), and tells this side which page it is.
// Kai's tab shows pages on this computer only (a dev server): it can't be sent, or wander, anywhere else,
// so nothing Kai reads in the repository can leave through it. It reads a page as its accessibility tree,
// clicks and types by the refs in that tree, takes screenshots, and reads the console: no scripts of its own.
// A person can turn all of it off (Browser → "…" → Let Kai use the browser).
import { session, webContents, type WebContents } from "electron";

import { loopback } from "./browserRules";
import { type AxNode, renderTree } from "./browserTree";
import type { Content, ToolSet } from "./mcp";

const OPEN_SECONDS = 15;
const LOAD_SECONDS = 30;
const CONSOLE_KEPT = 100;

const ref = { type: "integer", description: "The element's ref from the page's snapshot" };
const TOOLS: ReturnType<ToolSet["list"]> = [
  {
    name: "browser_navigate",
    description:
      "Open a page of the app running on this computer (localhost or 127.0.0.1 only) in your tab of the person's Browser pane, and read it. Returns the page's snapshot.",
    inputSchema: { type: "object", properties: { url: { type: "string", description: "For example http://localhost:3000/settings" } }, required: ["url"] },
  },
  {
    name: "browser_snapshot",
    description: "Read the page in your tab as it is now: its accessibility tree, with a ref on each element you can click or type into.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_click",
    description: "Click an element by its ref. Returns the page's snapshot afterwards.",
    inputSchema: { type: "object", properties: { ref }, required: ["ref"] },
  },
  {
    name: "browser_type",
    description: "Replace a field's text by its ref, and optionally press Enter. Returns the page's snapshot afterwards.",
    inputSchema: {
      type: "object",
      properties: { ref, text: { type: "string" }, submit: { type: "boolean", description: "Press Enter after typing" } },
      required: ["ref", "text"],
    },
  },
  {
    name: "browser_take_screenshot",
    description: "A picture of the page in your tab as the person sees it.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "browser_console_messages",
    description: "The page's recent console messages (errors and warnings first to look at after a change).",
    inputSchema: { type: "object", properties: {} },
  },
];

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
function within<T>(seconds: number, work: Promise<T>, late: string): Promise<T> {
  let timer: NodeJS.Timeout;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(late)), seconds * 1000);
  });
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer));
}

export class KaiBrowser implements ToolSet {
  private tab: WebContents | null = null;
  private asked: { id: number; url: string; done: (tab: WebContents) => void } | null = null;
  private serial = 0;
  /** Each tab's console for the page it shows now (heard from the tab's start, so a first load's messages are there too). */
  private readonly heard = new WeakMap<WebContents, string[]>();

  constructor(
    /** The app's own page (the pane lives in it), when its window is open there. */
    private readonly host: () => WebContents | null,
    private readonly allowed: () => boolean,
    private readonly partition: () => string,
  ) {}

  /** A tab of the pane, from its start: its console is kept (in memory, for the page it shows) in case it's Kai's. */
  hear(tab: WebContents): void {
    const said: string[] = [];
    this.heard.set(tab, said);
    tab.on("did-start-navigation", (details) => {
      if (details.isMainFrame && !details.isSameDocument) said.length = 0;
    });
    tab.on("console-message", (details) => {
      said.push(`[${details.level}] ${details.message}`.slice(0, 2000));
      if (said.length > CONSOLE_KEPT) said.shift();
    });
  }

  /** Whether a page is Kai's tab (its navigation is held to this computer: browser.ts `watch`). */
  owns(contents: WebContents): boolean {
    return contents === this.tab;
  }

  /** What Kai is waiting for the pane to open, for a pane that mounts after the request was sent. */
  get request(): { id: number; url: string } | null {
    return this.asked ? { id: this.asked.id, url: this.asked.url } : null;
  }

  /** The app's page says which of its tabs it made for a request. Checked: a tab of that page, in the pane's profile, on this computer. */
  ready(sender: WebContents, id: unknown, contentsId: unknown): void {
    const found = typeof contentsId === "number" ? webContents.fromId(contentsId) : undefined;
    if (!this.asked || this.asked.id !== id || !found || found.isDestroyed()) return;
    if (found.getType() !== "webview" || found.hostWebContents !== sender || found.session !== session.fromPartition(this.partition())) return;
    if (!loopback(found.getURL())) return;
    this.adopt(found);
    this.asked.done(found);
    this.asked = null;
  }

  list(): ReturnType<ToolSet["list"]> {
    return TOOLS;
  }

  async call(name: string, args: Record<string, unknown>): Promise<Content[]> {
    if (!this.allowed()) throw new Error("The person has turned off Kai's use of the Browser pane. Go on without it, and say what you couldn't check.");
    switch (name) {
      case "browser_navigate": {
        const url = typeof args.url === "string" ? args.url : "";
        if (!loopback(url))
          throw new Error("Only pages on this computer can be opened: an http://localhost:PORT or http://127.0.0.1:PORT address of the running app.");
        if (this.live()) await this.load(this.tab!, url);
        else await this.open(url);
        return this.page();
      }
      case "browser_snapshot":
        return this.page();
      case "browser_click": {
        const tab = this.mine();
        await this.click(tab, await this.centre(tab, args.ref));
        await this.settle(tab);
        return this.page();
      }
      case "browser_type": {
        const tab = this.mine();
        const node = this.node(args.ref);
        const typed = typeof args.text === "string" ? args.text : "";
        // As a person would: click into the field, select what it holds, type over it.
        await this.click(tab, await this.centre(tab, args.ref));
        await this.send(tab, "DOM.focus", node);
        const { object } = (await this.send(tab, "DOM.resolveNode", node)) as { object: { objectId: string } };
        const on = (functionDeclaration: string, ...values: string[]) =>
          this.send(tab, "Runtime.callFunctionOn", {
            objectId: object.objectId,
            functionDeclaration,
            arguments: values.map((value) => ({ value })),
            returnByValue: true,
          });
        await on("function () { if (typeof this.select === 'function') this.select(); }");
        await this.send(tab, "Input.insertText", { text: typed });
        // A field the typing didn't reach (the page hadn't taken focus yet) is set directly, with the events a framework listens for.
        await on(
          `function (text) {
            if (!("value" in this) || this.value === text) return;
            const proto = this instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : this instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, "value").set.call(this, text);
            this.dispatchEvent(new Event("input", { bubbles: true }));
            this.dispatchEvent(new Event("change", { bubbles: true }));
          }`,
          typed,
        );
        if (args.submit === true) {
          const enter = { key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 };
          await this.send(tab, "Input.dispatchKeyEvent", { ...enter, type: "keyDown", text: "\r" });
          await this.send(tab, "Input.dispatchKeyEvent", { ...enter, type: "keyUp" });
        }
        await this.settle(tab);
        return this.page();
      }
      case "browser_take_screenshot": {
        const shot = (await this.send(this.mine(), "Page.captureScreenshot", { format: "png" })) as { data: string };
        return [{ type: "image", data: shot.data, mimeType: "image/png" }];
      }
      case "browser_console_messages": {
        const said = this.heard.get(this.mine()) ?? [];
        return [{ type: "text", text: said.length ? said.join("\n") : "No console messages." }];
      }
      default:
        throw new Error(`No tool named ${name}`);
    }
  }

  private live(): boolean {
    if (this.tab?.isDestroyed()) this.tab = null;
    return this.tab !== null;
  }

  /** Kai's tab, still on this computer (a person can type another address into it: then it's theirs to bring back). */
  private mine(): WebContents {
    if (!this.live()) throw new Error("No page is open yet: open one with browser_navigate first.");
    if (!loopback(this.tab!.getURL())) throw new Error("Your tab has left the app on this computer. Open its page again with browser_navigate.");
    return this.tab!;
  }

  /** Ask the app's page for a tab at this address (it opens the session's Browser pane for it), and wait for it. */
  private async open(url: string): Promise<void> {
    const host = this.host();
    const nowhere =
      "The Browser pane couldn't be opened: the person needs this session open in Codes in the dotrix app. Go on without it, and say what you couldn't check.";
    if (!host || host.isDestroyed()) throw new Error(nowhere);
    const id = ++this.serial;
    const made = new Promise<WebContents>((resolve) => {
      this.asked = { id, url, done: resolve };
    });
    host.send("dotrix:browser:kai", { id, url });
    try {
      const tab = await within(OPEN_SECONDS, made, nowhere);
      await this.settle(tab);
    } finally {
      if (this.asked?.id === id) this.asked = null;
    }
  }

  private adopt(tab: WebContents): void {
    this.tab = tab;
    tab.once("destroyed", () => {
      if (this.tab === tab) this.tab = null;
    });
  }

  private async load(tab: WebContents, url: string): Promise<void> {
    try {
      await within(LOAD_SECONDS, tab.loadURL(url), `${url} didn't finish loading in ${LOAD_SECONDS} seconds.`);
    } catch (error) {
      throw new Error(`${url} couldn't be opened: ${error instanceof Error ? error.message : String(error)}. Is the app running on this computer?`);
    }
  }

  /** A click or a key can start a navigation or a render: give it a moment, then wait for loading to end. */
  private async settle(tab: WebContents): Promise<void> {
    await wait(350);
    for (let waited = 0; waited < 10_000 && !tab.isDestroyed() && tab.isLoading(); waited += 100) await wait(100);
  }

  private async send(tab: WebContents, method: string, params: Record<string, unknown> = {}): Promise<unknown> {
    if (!tab.debugger.isAttached()) {
      tab.debugger.attach("1.3");
      // The tab acts as the focused page even while the person works elsewhere in the app: typing reaches its field.
      await tab.debugger.sendCommand("Emulation.setFocusEmulationEnabled", { enabled: true });
    }
    return within(15, tab.debugger.sendCommand(method, params), `The page didn't answer (${method}).`);
  }

  private async click(tab: WebContents, point: { x: number; y: number }): Promise<void> {
    const mouse = { x: point.x, y: point.y, button: "left", clickCount: 1 };
    await this.send(tab, "Input.dispatchMouseEvent", { ...mouse, type: "mouseMoved" });
    await this.send(tab, "Input.dispatchMouseEvent", { ...mouse, type: "mousePressed" });
    await this.send(tab, "Input.dispatchMouseEvent", { ...mouse, type: "mouseReleased" });
  }

  private node(given: unknown): { backendNodeId: number } {
    if (typeof given !== "number" || !Number.isInteger(given) || given <= 0) throw new Error("Give the element's ref from the latest snapshot.");
    return { backendNodeId: given };
  }

  private async centre(tab: WebContents, given: unknown): Promise<{ x: number; y: number }> {
    const node = this.node(given);
    try {
      await this.send(tab, "DOM.scrollIntoViewIfNeeded", node);
      const { quads } = (await this.send(tab, "DOM.getContentQuads", node)) as { quads: number[][] };
      const quad = quads[0];
      if (!quad) throw new Error("not visible");
      return { x: (quad[0]! + quad[2]! + quad[4]! + quad[6]!) / 4, y: (quad[1]! + quad[3]! + quad[5]! + quad[7]!) / 4 };
    } catch {
      throw new Error(`Nothing to click at ref ${String(given)}: the page has changed, or the element isn't visible. Take a new snapshot.`);
    }
  }

  private async page(): Promise<Content[]> {
    const tab = this.mine();
    const { nodes } = (await this.send(tab, "Accessibility.getFullAXTree")) as { nodes: AxNode[] };
    return [{ type: "text", text: `Page: ${tab.getTitle()}\nURL: ${tab.getURL()}\n\n${renderTree(nodes)}` }];
  }
}
