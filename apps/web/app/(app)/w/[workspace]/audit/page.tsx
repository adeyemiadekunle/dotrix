import { redirect } from "next/navigation";

/** The audit log moved into Settings; keep old links working. */
export default async function Redirect({ params }: { params: Promise<{ workspace: string }> }) {
  const { workspace } = await params;
  redirect(`/w/${workspace}/settings/audit`);
}
