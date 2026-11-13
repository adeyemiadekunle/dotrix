import { EmptyState as AstryxEmptyState } from "@dotrix/ui/astryx";
import { type Icon } from "@phosphor-icons/react";
import type { ReactNode } from "react";
export function EmptyState({ icon: Icon, title, description, action }: { icon: Icon; title: string; description: string; action?: ReactNode }) {
  return <AstryxEmptyState icon={<Icon size={24} />} title={title} description={description} actions={action} headingLevel={2} />;
}
/** Also shown for things you can't see: the API answers 404 rather than revealing they exist. */
