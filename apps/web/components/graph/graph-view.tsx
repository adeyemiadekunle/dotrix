import { Button } from "@pmagent/ui/components/button";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { cn } from "@pmagent/ui/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRightIcon } from "lucide-react";
import { Link } from "@/lib/navigation";
import { useMemo, useState, type KeyboardEvent } from "react";

import { nodeHref } from "@/components/graph/related";
import { api, unwrap } from "@/lib/api";
import { LINK_LABELS } from "@/lib/graph";
import type { Scope } from "@/lib/issues";

const W = 720;
const H = 460;
const RINGS = [0, 150, 270];
const SQUASH = 0.62; // rings are ellipses: the view is wider than tall

const DOT: Record<string, string> = {
  document: "fill-primary",
  issue: "fill-warning",
  module: "fill-muted-foreground",
};

function short(text: string, max = 24): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/**
 * What's near a document, issue, or module, drawn: it in the middle, what links to it (either
 * way) on the first ring, and their links on the second, each near what it was reached from.
 * Click a node to centre on it.
 */
export function GraphView({
  scope,
  initialRef,
  projectBase,
}: {
  scope: Scope;
  initialRef: string;
  projectBase: string;
}) {
  const [center, setCenter] = useState(initialRef);
  const [depth, setDepth] = useState(2);
  const [hovered, setHovered] = useState<string | null>(null);
  const view = useQuery({
    queryKey: ["graph", scope.projectId, "view", center, depth],
    retry: false,
    refetchOnMount: "always",
    queryFn: () =>
      unwrap(
        api.GET("/v1/workspaces/{workspace_id}/projects/{project_id}/graph/view", {
          params: { path: { workspace_id: scope.workspaceId, project_id: scope.projectId }, query: { ref: center, depth } },
        }),
      ),
  });

  const placed = useMemo(() => {
    const at = new Map<string, { x: number; y: number; angle: number }>();
    const nodes = view.data?.nodes ?? [];
    const first = nodes.filter((n) => n.depth === 1);
    const step = (2 * Math.PI) / Math.max(1, first.length);
    for (const n of nodes) {
      if (n.depth === 0) at.set(n.ref, { x: W / 2, y: H / 2, angle: 0 });
    }
    first.forEach((n, i) => {
      const angle = -Math.PI / 2 + i * step;
      at.set(n.ref, { x: W / 2 + RINGS[1] * Math.cos(angle), y: H / 2 + RINGS[1] * SQUASH * Math.sin(angle), angle });
    });
    // Second ring: each node within its parent's slice, spread evenly there.
    const byParent = new Map<string, string[]>();
    for (const n of nodes.filter((n) => n.depth === 2)) {
      byParent.set(n.parent ?? "", [...(byParent.get(n.parent ?? "") ?? []), n.ref]);
    }
    for (const [parent, children] of byParent) {
      const base = at.get(parent)?.angle ?? 0;
      const width = Math.min(step * 0.9, Math.PI / 1.5);
      children.forEach((ref, i) => {
        const angle = base - width / 2 + (width * (i + 0.5)) / children.length;
        at.set(ref, { x: W / 2 + RINGS[2] * Math.cos(angle), y: H / 2 + RINGS[2] * SQUASH * Math.sin(angle), angle });
      });
    }
    return at;
  }, [view.data]);

  const centerNode = view.data?.nodes.find((n) => n.depth === 0);
  const centerHref = centerNode ? nodeHref(projectBase, centerNode) : null;

  function key(event: KeyboardEvent, ref: string) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setCenter(ref);
    }
  }

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Around</span>
        <span className="font-mono text-xs font-medium">{center}</span>
        {centerHref && (
          <Button size="sm" variant="ghost" className="h-7" asChild>
            <Link href={centerHref}>
              Open
              <ArrowUpRightIcon />
            </Link>
          </Button>
        )}
        {center !== initialRef && (
          <Button size="sm" variant="ghost" className="h-7" onClick={() => setCenter(initialRef)}>
            Back to {short(initialRef, 30)}
          </Button>
        )}
        <div role="group" aria-label="How far" className="bg-muted ml-auto flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
          {[1, 2].map((d) => (
            <button
              key={d}
              type="button"
              aria-pressed={depth === d}
              onClick={() => setDepth(d)}
              className={cn(
                "rounded-md px-2.5 py-1",
                depth === d ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {d === 1 ? "Direct links" : "Two steps"}
            </button>
          ))}
        </div>
      </div>

      {view.isLoading ? (
        <Skeleton className="h-80" />
      ) : view.isError || !view.data ? (
        <p className="text-muted-foreground text-sm">Nothing called {center} in this project&apos;s graph.</p>
      ) : view.data.nodes.length <= 1 ? (
        <p className="text-muted-foreground text-sm">Not linked to anything yet.</p>
      ) : (
        <div className="bg-card overflow-hidden rounded-xl border">
          <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label={`The project graph around ${center}`}>
            {view.data.edges.map((edge) => {
              const a = placed.get(edge.source);
              const b = placed.get(edge.target);
              if (!a || !b) return null;
              const lit = hovered !== null && (edge.source === hovered || edge.target === hovered);
              return (
                <line
                  key={`${edge.source}-${edge.kind}-${edge.target}`}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  strokeWidth={lit ? 1.75 : 1}
                  className={lit ? "stroke-primary" : "stroke-border"}
                >
                  <title>{`${edge.source} ${LINK_LABELS[edge.kind].out.toLowerCase()} ${edge.target}`}</title>
                </line>
              );
            })}
            {view.data.nodes.map((node) => {
              const p = placed.get(node.ref);
              if (!p) return null;
              const label = node.kind === "module" ? node.title : node.ref;
              return (
                <g
                  key={node.ref}
                  role="button"
                  tabIndex={0}
                  aria-label={`${label}: ${node.title}. Centre on it`}
                  className="cursor-pointer outline-none [&:focus-visible>circle]:stroke-ring"
                  onClick={() => setCenter(node.ref)}
                  onKeyDown={(e) => key(e, node.ref)}
                  onMouseEnter={() => setHovered(node.ref)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <title>{`${label}: ${node.title}${node.status ? ` (${node.status.replace("_", " ")})` : ""}`}</title>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={node.depth === 0 ? 11 : 7}
                    strokeWidth={2}
                    className={cn(DOT[node.kind], "stroke-background", node.status === "done" && "opacity-50")}
                  />
                  <text
                    x={p.x}
                    y={p.y + (node.depth === 0 ? 26 : 20)}
                    textAnchor="middle"
                    className={cn("fill-foreground text-[11px]", node.depth === 0 && "font-semibold")}
                  >
                    {short(label)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}
      <div className="text-muted-foreground flex flex-wrap items-center gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="bg-primary size-2.5 rounded-full" /> Document
        </span>
        <span className="flex items-center gap-1.5">
          <span className="bg-warning size-2.5 rounded-full" /> Issue
        </span>
        <span className="flex items-center gap-1.5">
          <span className="bg-muted-foreground size-2.5 rounded-full" /> Module
        </span>
        {view.data?.truncated && <span>Showing the nearest 60.</span>}
        <span className="ml-auto">Click a node to centre on it; hover a line to see the link.</span>
      </div>
    </div>
  );
}
