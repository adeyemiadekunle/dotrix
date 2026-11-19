import { Skeleton as AstryxSkeleton } from "@astryxdesign/core/Skeleton";
import type { ComponentProps } from "react";
export function Skeleton(props: ComponentProps<typeof AstryxSkeleton>) {
  return <AstryxSkeleton {...props} />;
}
