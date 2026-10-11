// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { htmlToMd, mdToHtml } from "./markdown";

describe("mdToHtml", () => {
  it("escapes HTML in the Markdown", () => {
    expect(mdToHtml('<img src=x onerror="alert(1)">')).toBe("<p>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;</p>");
  });

  it("renders bold, code, line breaks and paragraphs", () => {
    expect(mdToHtml("Fix **this** in `a.ts`\nnow\n\nThen")).toBe("<p>Fix <b>this</b> in <code>a.ts</code><br>now</p><p>Then</p>");
  });

  it("renders bulleted and numbered lists", () => {
    expect(mdToHtml("- a\n* b")).toBe("<ul><li>a</li><li>b</li></ul>");
    expect(mdToHtml("1. a\n2. b")).toBe("<ol><li>a</li><li>b</li></ol>");
  });
});

describe("htmlToMd", () => {
  it("turns the drawer's HTML back into Markdown", () => {
    expect(htmlToMd("<p><b>a</b> and <em>b</em> and <code>c</code></p><ul><li>x</li><li>y</li></ul>")).toBe("**a** and *b* and `c`\n\n- x\n- y");
  });

  it("numbers ordered lists", () => {
    expect(htmlToMd("<ol><li>one</li><li>two</li></ol>")).toBe("1. one\n2. two");
  });

  it("keeps what mdToHtml made", () => {
    const md = "Fix **this** in `a.ts`\n\n1. one\n2. two\n\n- x\n- y";
    expect(htmlToMd(mdToHtml(md))).toBe(md);
  });
});
