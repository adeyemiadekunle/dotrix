import { redirect } from "next/navigation";

/** The Docs tab became Files; keep old links working. */
export default async function Redirect({ params }: { params: Promise<{ workspace: string; project: string }> }) {
  const { workspace, project } = await params;
  redirect(`/w/${workspace}/p/${project}/files`);
}
