import { redirect } from "next/navigation";

/** Chat moved to the workspace (and summaries are asked for there); keep old links working. */
export default async function Redirect({
  params,
  searchParams,
}: {
  params: Promise<{ workspace: string; project: string }>;
  searchParams: Promise<{ thread?: string }>;
}) {
  const { workspace, project } = await params;
  const { thread } = await searchParams;
  redirect(`/w/${workspace}/chat?project=${project}${thread ? `&thread=${thread}` : ""}`);
}
