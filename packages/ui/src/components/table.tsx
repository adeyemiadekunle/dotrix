import {
  Table as AstryxTable,
  TableHeader as Header,
  TableBody as Body,
  TableRow as Row,
  TableHeaderCell as Head,
  TableCell as Cell,
} from "@astryxdesign/core/Table";
import type { ComponentProps } from "react";

// Keep the product's children-mode table API and data ownership.
export function Table(props: ComponentProps<"table">) {
  return <AstryxTable {...props} />;
}
export function TableHeader(props: ComponentProps<typeof Header>) {
  return <Header {...props} />;
}
export function TableBody(props: ComponentProps<typeof Body>) {
  return <Body {...props} />;
}
export function TableRow(props: ComponentProps<typeof Row>) {
  return <Row {...props} />;
}
export function TableHead(props: ComponentProps<typeof Head>) {
  return <Head {...props} />;
}
export function TableCell(props: ComponentProps<typeof Cell>) {
  return <Cell {...props} />;
}
