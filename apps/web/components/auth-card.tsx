import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@pmagent/ui/components/card";
import type { ReactNode } from "react";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xl">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
      {footer && <CardFooter className="text-muted-foreground justify-center text-sm">{footer}</CardFooter>}
    </Card>
  );
}
