import { cn } from "@pmagent/ui/lib/utils";
import { ChevronDownIcon, ChevronRightIcon, FileTextIcon, FolderIcon, FolderOpenIcon, Trash2Icon } from "lucide-react";
import { useState } from "react";

import type { TreeNode } from "@/lib/knowledge";

function Node({
  node,
  depth,
  selected,
  onSelect,
  open,
  toggle,
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  open: Set<string>;
  toggle: (path: string) => void;
}) {
  const pad = { paddingLeft: `${depth * 12 + 8}px` };
  if (node.children) {
    const isOpen = open.has(node.path);
    return (
      <li>
        <button
          type="button"
          onClick={() => toggle(node.path)}
          aria-expanded={isOpen}
          className="hover:bg-muted flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-sm"
          style={pad}
        >
          {isOpen ? <ChevronDownIcon className="size-3.5 shrink-0" /> : <ChevronRightIcon className="size-3.5 shrink-0" />}
          {isOpen ? (
            <FolderOpenIcon className="text-muted-foreground size-4 shrink-0" />
          ) : (
            <FolderIcon className="text-muted-foreground size-4 shrink-0" />
          )}
          <span className="truncate">{node.name}</span>
        </button>
        {isOpen && (
          <ul>
            {node.children.map((child) => (
              <Node key={child.path} node={child} depth={depth + 1} {...{ selected, onSelect, open, toggle }} />
            ))}
          </ul>
        )}
      </li>
    );
  }
  const deleted = node.file?.deleted;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        aria-current={selected === node.path ? "page" : undefined}
        className={cn(
          "hover:bg-muted flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-sm",
          selected === node.path && "bg-muted font-medium",
          deleted && "text-muted-foreground line-through",
        )}
        style={{ paddingLeft: `${depth * 12 + 8 + 18}px` }}
      >
        {deleted ? (
          <Trash2Icon className="size-4 shrink-0" />
        ) : (
          <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
    </li>
  );
}

/** Folders of `.pmagent/`, expanded along the way to the selected file. */
export function FileTree({
  nodes,
  selected,
  onSelect,
  filtering,
}: {
  nodes: TreeNode[];
  selected: string | null;
  onSelect: (path: string) => void;
  /** While searching, every folder is shown open. */
  filtering: boolean;
}) {
  const [open, setOpen] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    const parts = selected?.split("/") ?? [];
    for (let i = 1; i < parts.length; i++) initial.add(parts.slice(0, i).join("/"));
    return initial;
  });
  const toggle = (path: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const allOpen = new Set<string>();
  if (filtering) {
    const walk = (list: TreeNode[]) =>
      list.forEach((n) => {
        if (n.children) {
          allOpen.add(n.path);
          walk(n.children);
        }
      });
    walk(nodes);
  }

  return (
    <ul className="grid gap-px">
      {nodes.map((node) => (
        <Node
          key={node.path}
          node={node}
          depth={0}
          selected={selected}
          onSelect={onSelect}
          open={filtering ? allOpen : open}
          toggle={toggle}
        />
      ))}
    </ul>
  );
}
