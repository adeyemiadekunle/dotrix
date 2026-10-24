// What Kai did in a coding turn, for the panel beside a conversation or a session
// (components/KaiPanel.tsx): its diff as files and hunks, the repository's paths as a tree, and its
// commands with their output.

interface DiffLine {
  kind: "add" | "del" | "ctx";
  text: string;
  old: number | null; // its line number before (none for an added line)
  new: number | null; // and after (none for a removed one)
}
export interface DiffHunk {
  header: string;
  lines: DiffLine[];
}
export interface DiffFile {
  path: string;
  status: "added" | "deleted" | "modified";
  binary: boolean;
  added: number;
  removed: number;
  hunks: DiffHunk[];
}

const unquote = (p: string) => (p.startsWith('"') && p.endsWith('"') ? p.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\") : p);

/** A unified diff (`git diff --binary`, as each turn keeps it) as files and their hunks, with line numbers. */
export function parseDiff(diff: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNo = 0;
  let newNo = 0;
  // Lines a hunk still has (from its header): while it has any, every line is its content, even one
  // that starts "+++" or "---" (an added "++x", a removed "--" rule), never a file's header.
  let oldLeft = 0;
  let newLeft = 0;
  for (const line of diff.split("\n")) {
    if (hunk && file && !file.binary && (oldLeft > 0 || newLeft > 0)) {
      if (line.startsWith("+")) {
        hunk.lines.push({ kind: "add", text: line.slice(1), old: null, new: newNo++ });
        file.added++;
        newLeft--;
      } else if (line.startsWith("-")) {
        hunk.lines.push({ kind: "del", text: line.slice(1), old: oldNo++, new: null });
        file.removed++;
        oldLeft--;
      } else if (line.startsWith(" ") || line === "") {
        hunk.lines.push({ kind: "ctx", text: line.slice(1), old: oldNo++, new: newNo++ });
        oldLeft--;
        newLeft--;
      }
      continue; // "\ No newline at end of file" and the like: not a line of the file
    }
    if (line.startsWith("diff --git ")) {
      const m = line.match(/^diff --git ("?)a\/(.+?)\1 ("?)b\/(.+?)\3$/);
      file = { path: unquote(m ? m[4]! : line.slice(11)), status: "modified", binary: false, added: 0, removed: 0, hunks: [] };
      files.push(file);
      hunk = null;
    } else if (!file) {
      continue;
    } else if (line.startsWith("new file mode")) {
      file.status = "added";
    } else if (line.startsWith("deleted file mode")) {
      file.status = "deleted";
    } else if (line.startsWith("GIT binary patch") || line.startsWith("Binary files ")) {
      file.binary = true;
    } else if (line.startsWith("@@")) {
      const m = line.match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/);
      oldNo = m ? Number(m[1]) : 0;
      newNo = m ? Number(m[3]) : 0;
      oldLeft = m ? Number(m[2] ?? 1) : 0;
      newLeft = m ? Number(m[4] ?? 1) : 0;
      hunk = { header: line, lines: [] };
      file.hunks.push(hunk);
    }
  }
  return files;
}

export interface TreeNode {
  name: string;
  path: string; // a folder's path ends without a slash; the root's is ""
  file?: { status: string; size: number | null };
  children: TreeNode[];
  changed: number; // files under it the turn changed
}

/** Paths as a tree: folders first, then files, each by name; each folder counts its changed files. */
export function buildTree(entries: { path: string; status: string; size: number | null }[]): TreeNode {
  const root: TreeNode = { name: "", path: "", children: [], changed: 0 };
  for (const e of entries) {
    const parts = e.path.split("/");
    let node = root;
    const changed = e.status !== "unchanged";
    if (changed) root.changed++;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join("/");
      let next = node.children.find((c) => c.name === part && Boolean(c.file) === (i === parts.length - 1));
      if (!next) {
        next = { name: part, path, children: [], changed: 0, ...(i === parts.length - 1 ? { file: { status: e.status, size: e.size } } : {}) };
        node.children.push(next);
      }
      if (changed && i < parts.length - 1) next.changed++;
      node = next;
    });
  }
  const sort = (n: TreeNode) => {
    n.children.sort((a, b) => Number(Boolean(a.file)) - Number(Boolean(b.file)) || a.name.localeCompare(b.name));
    n.children.forEach(sort);
  };
  sort(root);
  return root;
}

export interface TerminalEntry {
  ref: string | null;
  command: string;
  output: string | null; // null: none yet (still running), or the turn didn't keep it
  failed: boolean;
  at: string;
}

/** A turn's commands, each with its output (paired by `ref`), in the order they ran. */
export function terminal(events: { kind: string; text: string; at: string; ref?: string | null }[]): TerminalEntry[] {
  const out: TerminalEntry[] = [];
  const byRef = new Map<string, TerminalEntry>();
  for (const e of events) {
    if (e.kind === "tool" && e.text.startsWith("Ran ")) {
      const entry: TerminalEntry = { ref: e.ref ?? null, command: e.text.slice(4), output: null, failed: false, at: e.at };
      out.push(entry);
      if (e.ref) byRef.set(e.ref, entry);
    } else if ((e.kind === "output" || e.kind === "output-error") && e.ref && byRef.has(e.ref)) {
      const entry = byRef.get(e.ref)!;
      entry.output = (entry.output ? entry.output + "\n" : "") + e.text;
      entry.failed = entry.failed || e.kind === "output-error";
    }
  }
  return out;
}
