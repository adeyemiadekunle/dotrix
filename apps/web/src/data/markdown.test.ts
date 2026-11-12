// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { editorCanKeep, htmlToMd, mdToHtml } from "./markdown";

describe("mdToHtml", () => {
  it("escapes HTML in the Markdown", () => {
    expect(mdToHtml('<img src=x onerror="alert(1)">')).toBe('<p>&lt;img src=x onerror="alert(1)"&gt;</p>');
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

describe("round trips", () => {
  it.each([
    ["a paragraph", "Just some text"],
    ["bold", "Some **bold** text"],
    ["code", "Run `pnpm test` now"],
    ["a bulleted list", "- one\n- two"],
    ["a numbered list", "1. one\n2. two"],
  ])("keeps %s", (_name, md) => {
    expect(htmlToMd(mdToHtml(md))).toBe(md);
  });

  it("keeps a link's address", () => {
    expect(htmlToMd('<p><a href="https://example.com">site</a></p>')).toContain("https://example.com");
  });

  it("keeps a heading on its own line", () => {
    expect(htmlToMd("<h4>Title</h4><p>Body</p>")).toMatch(/Title\n+Body/);
  });

  it("survives the browser's innerHTML with quotes, ampersands and angle brackets", () => {
    for (const md of ['say "hi"', "a & b < c > d", "x &amp; y"]) {
      const el = document.createElement("div");
      el.innerHTML = mdToHtml(md);
      expect(el.innerHTML).toBe(mdToHtml(md));
    }
  });

  it.each([
    ["a link", "See [the site](https://example.com/a?b=1&c=2) now"],
    ["h1", "# One\n\nBody"],
    ["h2", "## Two\n\nBody"],
    ["h3", "### Three\n\nBody"],
    ["h4", "#### Four\n\nBody"],
    ["h5", "##### Five\n\nBody"],
    ["h6", "###### Six\n\nBody"],
    ["italics", "Some *slanted* text"],
    ["a nested list", "- a\n  - b\n  - c\n- d"],
    ["a mix", "## Plan\n\nDo **this** and *that* with [docs](https://x.dev)\n\n1. one\n2. two\n\n- x\n  - y"],
  ])("keeps %s", (_name, md) => {
    expect(htmlToMd(mdToHtml(md))).toBe(md);
  });

  it("reads _italic_ like *italic*", () => {
    expect(mdToHtml("an _odd_ one and snake_case_name")).toBe("<p>an <i>odd</i> one and snake_case_name</p>");
  });
});

describe("safety", () => {
  it("writes no link for an unsafe address", () => {
    expect(mdToHtml("[x](javascript:alert(1))")).not.toContain("href");
  });

  it("never turns the Markdown's own text into a tag", () => {
    expect(mdToHtml("<img src=x onerror=1>")).not.toContain("<img");
  });

  it("escapes quotes in a link's address", () => {
    const html = mdToHtml('[x](https://a.com/"onmouseover=1)');
    const el = document.createElement("div");
    el.innerHTML = html;
    expect(el.querySelector("a")?.getAttributeNames().sort()).toEqual(["href", "rel", "target"]);
  });
});

describe("editorCanKeep", () => {
  it.each([
    ["", true],
    ["Plain **text** with [a link](https://x.dev)", true],
    ["* agent bullet\n* another", true],
    ["- a\n  - b", true],
    ["Spelled _differently_ than the editor writes it", true],
    ["Extra\n\n\n\nblank lines", true],
    ["| a | b |\n| - | - |\n| 1 | 2 |", false],
    ["```ts\nconst a = 1;\n```", false],
  ])("%j -> %s", (md, ok) => {
    expect(editorCanKeep(md)).toBe(ok);
  });
});
