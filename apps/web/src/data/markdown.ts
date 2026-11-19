// Issue descriptions: Markdown from the API <-> the drawer's rich text (HTML).

const SAFE_LINK = /^(https?:|mailto:)/i;

/**
 * Markdown from the API, shown by the drawer's rich text (HTML).
 * Paragraphs, headings, nested lists, bold, italics, code and links. The output is assigned to `innerHTML`, so every tag
 * is written here: text from the Markdown is escaped and never becomes a tag or an attribute.
 */
export function mdToHtml(md: string): string {
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
  const inline = (raw: string) => {
    // Code spans and links are set aside so nothing inside them is formatted again.
    const stash: string[] = [];
    const keep = (html: string) => `\u0000${stash.push(html) - 1}\u0000`;
    const s = esc(raw)
      .replace(/`(.+?)`/g, (_m, code: string) => keep(`<code>${code}</code>`))
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, url: string) =>
        SAFE_LINK.test(url) ? keep(`<a href="${url.replace(/"/g, "&quot;")}" target="_blank" rel="noopener noreferrer">${text}</a>`) : text,
      )
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/\*(?!\s)(.+?)(?<!\s)\*/g, "<i>$1</i>")
      .replace(/(^|[^\w])_(?!\s)(.+?)(?<!\s)_(?!\w)/g, "$1<i>$2</i>");
    // eslint-disable-next-line no-control-regex
    return s.replace(/\u0000(\d+)\u0000/g, (_m, i: string) => stash[Number(i)]);
  };
  const item = /^(\s*)([-*]|\d+\.) (.*)$/;
  const blockHtml = (lines: string[]) => {
    let html = "";
    let para: string[] = [];
    const stack: { type: string; level: number }[] = [];
    const closeTop = () => {
      html += `</li></${stack.pop()!.type}>`;
    };
    const flushPara = () => {
      if (para.length) html += `<p>${para.map(inline).join("<br>")}</p>`;
      para = [];
    };
    const flushList = () => {
      while (stack.length) closeTop();
    };
    for (const line of lines) {
      const h = /^(#{1,6}) +(.*)$/.exec(line);
      const m = item.exec(line);
      if (h) {
        flushPara();
        flushList();
        html += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`;
      } else if (m) {
        flushPara();
        const level = Math.floor(m[1].replace(/\t/g, "  ").length / 2);
        const type = /\d/.test(m[2]) ? "ol" : "ul";
        while (stack.length && stack[stack.length - 1].level > level) closeTop();
        const top = stack[stack.length - 1];
        if (top && top.level === level && top.type === type) html += "</li>";
        else {
          if (top && top.level === level) closeTop();
          html += `<${type}>`;
          stack.push({ type, level });
        }
        html += `<li>${inline(m[3])}`;
      } else {
        flushList();
        para.push(line);
      }
    }
    flushPara();
    flushList();
    return html;
  };
  return md
    .replaceAll("\u0000", "")
    .trim()
    .split(/\n{2,}/)
    .map((block) => blockHtml(block.split("\n")))
    .join("");
}

/** The drawer's HTML back to Markdown for the API. */
export function htmlToMd(html: string): string {
  const el = document.createElement("div");
  el.innerHTML = html;
  const isList = (n: Node) => n.nodeName === "UL" || n.nodeName === "OL";
  const walk = (n: Node, depth = 0): string => {
    if (n.nodeType === Node.TEXT_NODE) return n.textContent ?? "";
    const e = n as HTMLElement;
    const kids = () => [...e.childNodes].map((c) => walk(c, depth)).join("");
    switch (e.tagName) {
      case "B":
      case "STRONG":
        return `**${kids()}**`;
      case "I":
      case "EM":
        return `*${kids()}*`;
      case "CODE":
        return `\`${kids()}\``;
      case "A": {
        const href = e.getAttribute("href") ?? "";
        return SAFE_LINK.test(href) ? `[${kids()}](${href})` : kids();
      }
      case "BR":
        return "\n";
      case "LI": {
        const own = [...e.childNodes]
          .filter((c) => !isList(c))
          .map((c) => walk(c, depth))
          .join("")
          .replace(/\n+$/, "");
        const nested = [...e.childNodes]
          .filter(isList)
          .map((c) => walk(c, depth + 1))
          .join("");
        const marker = e.parentElement?.tagName === "OL" ? `${[...e.parentElement.children].indexOf(e) + 1}.` : "-";
        return `${"  ".repeat(Math.max(depth - 1, 0))}${marker} ${own}\n${nested}`;
      }
      case "UL":
      case "OL": {
        const inner = [...e.childNodes].map((c) => walk(c, depth === 0 ? 1 : depth)).join("");
        return e.parentElement?.tagName === "LI" ? inner : `${inner}\n`;
      }
      case "H1":
      case "H2":
      case "H3":
      case "H4":
      case "H5":
      case "H6":
        return `${"#".repeat(Number(e.tagName[1]))} ${kids()}\n\n`;
      case "P":
      case "DIV":
        return `${kids()}\n\n`;
      default:
        return kids();
    }
  };
  return walk(el)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Whether the drawer's editor can save this Markdown without losing or rewriting anything (no tables or fenced code, and it round-trips). */
export function editorCanKeep(md: string): boolean {
  if (/^\s*(```|~~~)/m.test(md) || /^\s*\|.*\|\s*$/m.test(md)) return false;
  // What the editor would save may be spelled differently (`_x_` as `*x*`, fewer blank lines);
  // it's kept if it shows the same as the original.
  const shown = mdToHtml(md);
  return mdToHtml(htmlToMd(shown)) === shown;
}
