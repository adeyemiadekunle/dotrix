"use client";

import * as React from "react";
import { ChevronRightIcon, FileIcon, FolderIcon } from "lucide-react";

import { Button } from "@dotrix/ui/components/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@dotrix/ui/components/collapsible";
import { cn } from "@dotrix/ui/lib/utils";

export type FileTreeNodeData = { type: "file"; name: string; path: string } | { type: "folder"; name: string; path: string; children: FileTreeNodeData[] };

function TreeNode({ node, selected, onSelect, depth = 0 }: { node: FileTreeNodeData; selected?: string; onSelect?: (path: string) => void; depth?: number }) {
  const style = { paddingLeft: depth * 14 };

  if (node.type === "folder") {
    return (
      <Collapsible defaultOpen>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="w-full justify-start font-normal" style={style}>
            <ChevronRightIcon className="transition-transform group-data-[state=open]/collapsible:rotate-90" />
            <FolderIcon />
            <span className="truncate">{node.name}</span>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="flex flex-col">
            {node.children.map((child) => (
              <TreeNode key={child.path} node={child} selected={selected} onSelect={onSelect} depth={depth + 1} />
            ))}
          </div>
        </CollapsibleContent>
      </Collapsible>
    );
  }

  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn("w-full justify-start font-normal", selected === node.path && "bg-accent text-accent-foreground")}
      style={style}
      aria-current={selected === node.path ? "true" : undefined}
      onClick={() => onSelect?.(node.path)}
    >
      <FileIcon />
      <span className="truncate">{node.name}</span>
    </Button>
  );
}

/**
 * The files the agent changed, as a folder tree (shadcn/ui AI Elements File Tree). Folders
 * collapse; files report their path through `onSelect`.
 */
function FileTree({
  nodes,
  selected,
  onSelect,
  className,
}: {
  nodes: FileTreeNodeData[];
  selected?: string;
  onSelect?: (path: string) => void;
  className?: string;
}) {
  return (
    <div className={cn("flex w-full flex-col text-sm", className)}>
      {nodes.map((node) => (
        <TreeNode key={node.path} node={node} selected={selected} onSelect={onSelect} />
      ))}
    </div>
  );
}

export { FileTree };
