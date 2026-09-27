import { redirect } from "next/navigation";

/** A project opens on its board. */
export default async function ProjectHome({ params }: { params: Promise<{ workspace: string; project: string }> }) {
  const { workspace, project } = await params;
  redirect(`/w/${workspace}/p/${project}/board`);
}
