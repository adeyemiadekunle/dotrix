"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import type { ReactNode } from "react";

import { PROJECT_SOURCE_LABELS } from "@/lib/labels";
import { useCurrentProject } from "@/lib/queries";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-4 py-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export default function ProjectOverview() {
  const { project, isLoading } = useCurrentProject();

  return (
    <>
      <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
        {isLoading || !project ? (
          <Skeleton className="h-64 max-w-2xl" />
        ) : (
          <Card className="max-w-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono">
                  {project.key}
                </Badge>
                {project.name}
              </CardTitle>
              {project.description && <p className="text-muted-foreground text-sm">{project.description}</p>}
            </CardHeader>
            <CardContent>
              <dl className="divide-y">
                <Row label="Started from">{PROJECT_SOURCE_LABELS[project.source]}</Row>
                <Row label="Repository">
                  {project.repo_url?.startsWith("https://") ? (
                    <a href={project.repo_url} target="_blank" rel="noreferrer" className="underline underline-offset-4">
                      {project.repo_url}
                    </a>
                  ) : (
                    <span className="text-muted-foreground">{project.repo_url ?? "Not connected"}</span>
                  )}
                </Row>
                <Row label="Agent model">
                  <code className="font-mono text-xs">{project.model}</code>
                </Row>
                <Row label="Knowledge">Revision {project.knowledge_revision}</Row>
                <Row label="Created">{new Date(project.created_at).toLocaleDateString()}</Row>
              </dl>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
