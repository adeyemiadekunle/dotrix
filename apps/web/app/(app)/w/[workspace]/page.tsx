"use client";

import { Badge } from "@pmagent/ui/components/badge";
import { Button } from "@pmagent/ui/components/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import { Skeleton } from "@pmagent/ui/components/skeleton";
import { FolderPlusIcon, PlusIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app-shell";
import { CreateProjectDialog } from "@/components/create-project-dialog";
import { EmptyState, NotFound } from "@/components/states";
import { PROJECT_SOURCE_LABELS, ROLE_LABELS, canManageProjects, withArticle } from "@/lib/labels";
import { useCurrentWorkspace, useProjects } from "@/lib/queries";

export default function WorkspaceHome() {
  const { workspace, notFound } = useCurrentWorkspace();
  const projects = useProjects(workspace?.id);
  const [creating, setCreating] = useState(false);

  if (notFound) return <NotFound what="workspace" />;
  const canCreate = canManageProjects(workspace?.role);

  return (
    <>
      <PageHeader
        title="Projects"
        parent={workspace?.name}
        actions={
          canCreate && (
            <Button size="sm" onClick={() => setCreating(true)}>
              <PlusIcon />
              New project
            </Button>
          )
        }
      />
      <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
        {workspace && (
          <p className="text-muted-foreground text-sm">
            {workspace.via_organization
              ? `You see ${workspace.name} as an owner because you own its organisation.`
              : `You're ${withArticle(ROLE_LABELS[workspace.role].toLowerCase())} in ${workspace.name}.`}
          </p>
        )}
        {projects.isLoading && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }, (_, i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        )}
        {projects.data?.length === 0 && (
          <EmptyState
            icon={FolderPlusIcon}
            title="Start your first project"
            description={
              canCreate
                ? "Create a project from your docs, or run pmagent connect inside a repo to start from its code."
                : "An owner or admin creates projects. Once there is one, it appears here."
            }
            action={
              canCreate && (
                <Button onClick={() => setCreating(true)}>
                  <PlusIcon />
                  New project
                </Button>
              )
            }
          />
        )}
        {projects.data && projects.data.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {projects.data.map((project) => (
              <Link key={project.id} href={`/w/${workspace!.slug}/p/${project.key}`} className="group">
                <Card className="group-hover:border-foreground/20 h-full transition-colors">
                  <CardHeader>
                    <div className="flex min-w-0 items-center gap-2">
                      <Badge variant="outline" className="font-mono">
                        {project.key}
                      </Badge>
                      <CardTitle className="min-w-0 truncate">{project.name}</CardTitle>
                    </div>
                    <CardDescription className="line-clamp-2">
                      {project.description || PROJECT_SOURCE_LABELS[project.source]}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
      {workspace && <CreateProjectDialog workspace={workspace} open={creating} onOpenChange={setCreating} />}
    </>
  );
}
