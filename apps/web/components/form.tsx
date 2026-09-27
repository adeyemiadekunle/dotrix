"use client";

import { Alert, AlertDescription } from "@pmagent/ui/components/alert";
import { Button } from "@pmagent/ui/components/button";
import { Input } from "@pmagent/ui/components/input";
import { Label } from "@pmagent/ui/components/label";
import { AlertCircleIcon, Loader2Icon } from "lucide-react";
import { useId, type ComponentProps, type ReactNode } from "react";

export function Field({
  label,
  hint,
  action,
  ...input
}: ComponentProps<typeof Input> & { label: string; hint?: ReactNode; action?: ReactNode }) {
  const id = useId();
  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between">
        <Label htmlFor={id}>{label}</Label>
        {action}
      </div>
      <Input id={id} {...input} />
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

export function SubmitButton({ pending, children, ...props }: ComponentProps<typeof Button> & { pending: boolean }) {
  return (
    <Button type="submit" disabled={pending} {...props}>
      {pending && <Loader2Icon className="animate-spin" />}
      {children}
    </Button>
  );
}

export function FormError({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <Alert variant="destructive">
      <AlertCircleIcon />
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
