import { Button } from "@dotrix/ui/components/button";
import { Input } from "@dotrix/ui/components/input";
import { Label } from "@dotrix/ui/components/label";
import { AlertCircleIcon, Loader2Icon } from "lucide-react";
import { useId, type ComponentProps, type ReactNode } from "react";

export function Field({ label, hint, action, ...input }: ComponentProps<typeof Input> & { label: string; hint?: ReactNode; action?: ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <div className="row">
        <Label htmlFor={id} className="label">
          {label}
        </Label>
        <span className="sp" />
        {action}
      </div>
      <Input id={id} {...input} className={`input-lg ${input.className ?? ""}`} />
      {hint && <span className="hint">{hint}</span>}
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
    <div className="alert danger" role="alert">
      <AlertCircleIcon size={15} />
      <span>{message}</span>
    </div>
  );
}

/**
 * The save controls of a form with changes: a compact bar at the form's bottom right that stays
 * in view while you scroll (sticky), and isn't there at all while nothing has changed.
 */
