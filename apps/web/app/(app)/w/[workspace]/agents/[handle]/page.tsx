import { redirect } from "next/navigation";

/** Agents moved into Settings; keep old links working. */
export default async function Redirect({ params }: { params: Promise<{ workspace: string; handle: string }> }) {
  const { workspace, handle } = await params;
  redirect(`/w/${workspace}/settings/agents/${handle}`);
}
