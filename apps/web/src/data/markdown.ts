// Issue descriptions: Markdown from the API <-> the drawer's rich text (HTML).

/** Markdown from the API, shown by the drawer's rich text (HTML). Plain paragraphs and lists. */
export function mdToHtml(md: string): string {
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
  const inline = (s: string) =>
    esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`(.+?)`/g, "<code>$1</code>");
  return md
    .trim()
    .split(/\n{2,}/)
    .map((block) => {
      const lines = block.split("\n");
      if (lines.every((l) => /^\s*[-*] /.test(l))) return `<ul>${lines.map((l) => `<li>${inline(l.replace(/^\s*[-*] /, ""))}</li>`).join("")}</ul>`;
      if (lines.every((l) => /^\s*\d+\. /.test(l))) return `<ol>${lines.map((l) => `<li>${inline(l.replace(/^\s*\d+\. /, ""))}</li>`).join("")}</ol>`;
      return `<p>${lines.map(inline).join("<br>")}</p>`;
    })
    .join("");
}
/** The drawer's HTML back to Markdown for the API. */
export function htmlToMd(html: string): string {
  const el = document.createElement("div");
  el.innerHTML = html;
  const walk = (n: Node): string => {
    if (n.nodeType === Node.TEXT_NODE) return n.textContent ?? "";
    const e = n as HTMLElement;
    const kids = [...e.childNodes].map(walk).join("");
    switch (e.tagName) {
      case "B":
      case "STRONG":
        return `**${kids}**`;
      case "I":
      case "EM":
        return `*${kids}*`;
      case "CODE":
        return `\`${kids}\``;
      case "BR":
        return "\n";
      case "LI":
        return e.parentElement?.tagName === "OL" ? `${[...e.parentElement.children].indexOf(e) + 1}. ${kids}\n` : `- ${kids}\n`;
      case "UL":
      case "OL":
        return `${kids}\n`;
      case "P":
      case "DIV":
      case "H1":
      case "H2":
      case "H3":
        return `${kids}\n\n`;
      default:
        return kids;
    }
  };
  return walk(el)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
