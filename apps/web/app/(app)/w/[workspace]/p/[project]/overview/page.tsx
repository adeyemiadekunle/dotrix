import { redirect } from "next/navigation";

/** The Overview tab became Settings; keep old links working. */
export default async function OverviewRedirect({ params }: { params: Promise<{ workspace: string; project: string }> }) {
  const { workspace, project } = await params;
  redirect(`/w/${workspace}/p/${project}/settings`);
}
