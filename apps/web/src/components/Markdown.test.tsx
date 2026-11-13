// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { Markdown } from "@/components/markdown";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: ReturnType<typeof createRoot> | undefined;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

it("uses Astryx inline code while keeping file-path actions and literal code text", () => {
  const host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const openFile = vi.fn();
  act(() =>
    root!.render(
      <Markdown onCode={(code) => (code === "src/main.ts" ? openFile : undefined)}>{'Open `src/main.ts`; compare `const html = "<b>literal</b>"`.'}</Markdown>,
    ),
  );
  const codes = host.querySelectorAll("code.astryx-code");
  expect(codes).toHaveLength(2);
  expect(codes[1]!.textContent).toBe('const html = "<b>literal</b>"');
  expect(codes[1]!.querySelector("b")).toBeNull();
  const path = host.querySelector<HTMLButtonElement>("button.path-link")!;
  expect(path.type).toBe("button");
  expect(path.querySelector(".astryx-code")?.textContent).toBe("src/main.ts");
  act(() => path.click());
  expect(openFile).toHaveBeenCalledOnce();
});
