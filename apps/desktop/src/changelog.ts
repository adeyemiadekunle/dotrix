// What's new: the releases in CHANGELOG.md (bundled with the app), newest first, for the web app's What's
// new window. No Electron here, so it's tested on its own (changelog.test.ts).
import fs from "node:fs";
import path from "node:path";

export interface Release {
  version: string; // "0.2.0", or "Unreleased" in a development build
  date: string | null; // "2026-11-01"
  sections: { title: string; items: string[] }[]; // "Added", "Fixed", …, each a list of Markdown items
}

/** The releases in a Keep a Changelog file: `## [X.Y.Z] - date`, then `### Section`, then `- item` lines
 *  (an item's continuation lines are indented). Unreleased only when asked for (development builds). */
export function parseChangelog(text: string, { unreleased = false } = {}): Release[] {
  const releases: Release[] = [];
  let release: Release | null = null;
  let section: Release["sections"][number] | null = null;
  for (const line of text.split(/\r?\n/)) {
    const head = line.match(/^## \[([^\]]+)\](?:\s*-\s*(\S+))?/);
    if (head) {
      release = { version: head[1]!, date: head[2] ?? null, sections: [] };
      section = null;
      if (unreleased || head[1]!.toLowerCase() !== "unreleased") releases.push(release);
      continue;
    }
    if (!release) continue;
    const sub = line.match(/^### (.+)/);
    if (sub) {
      section = { title: sub[1]!.trim(), items: [] };
      release.sections.push(section);
      continue;
    }
    if (!section) continue;
    const item = line.match(/^[-*] (.*)/);
    if (item) section.items.push(item[1]!.trim());
    else if (/^\s+\S/.test(line) && section.items.length) section.items[section.items.length - 1] += ` ${line.trim()}`;
  }
  for (const r of releases) r.sections = r.sections.filter((s) => s.items.length);
  return releases.filter((r) => r.sections.length);
}

/** The bundled CHANGELOG.md: in a release, beside the app's resources; developing, the repository's. */
export function readChangelog(resources: string | undefined, packaged: boolean, limit = 10): Release[] {
  const candidates = [resources && path.join(resources, "CHANGELOG.md"), path.join(__dirname, "..", "..", "..", "CHANGELOG.md")];
  for (const file of candidates) {
    if (!file) continue;
    try {
      return parseChangelog(fs.readFileSync(file, "utf8"), { unreleased: !packaged }).slice(0, limit);
    } catch {
      // the next place
    }
  }
  return [];
}
