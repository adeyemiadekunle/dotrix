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

/**
 * The save controls of a form with changes: a compact bar at the form's bottom right that stays
 * in view while you scroll (sticky), and isn't there at all while nothing has changed.
 */
export function SaveBar({
  dirty,
  pending,
  onDiscard,
  label = "Save changes",
}: {
  dirty: boolean;
  pending: boolean;
  onDiscard: () => void;
  label?: string;
}) {
  if (!dirty) return null;
  return (
    <div
      role="status"
      className="bg-foreground text-background sticky bottom-4 z-10 flex w-fit items-center gap-2 justify-self-end rounded-xl py-1.5 pr-1.5 pl-3.5 text-sm shadow-lg"
    >
      <span className="mr-1.5">Unsaved changes</span>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="text-background/80 hover:bg-background/10 hover:text-background"
        disabled={pending}
        onClick={onDiscard}
      >
        Discard
      </Button>
      <SubmitButton pending={pending} size="sm">
        {label}
      </SubmitButton>
    </div>
  );
}
