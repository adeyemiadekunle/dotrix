import { Button } from "@dotrix/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@dotrix/ui/components/dialog";
import { Loader2Icon } from "lucide-react";
import { useState, type ReactNode } from "react";

export interface ConfirmRequest {
  title: string;
  description: ReactNode;
  confirm: string;
  destructive?: boolean;
  action: () => Promise<unknown>;
}

/** A single confirmation dialog driven by `ask(...)`; closes when the action succeeds. */
export function useConfirm(): [(request: ConfirmRequest) => void, ReactNode] {
  const [request, setRequest] = useState<ConfirmRequest | null>(null);
  const [pending, setPending] = useState(false);

  const dialog = (
    <Dialog open={Boolean(request)} onOpenChange={(open) => !open && !pending && setRequest(null)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{request?.title}</DialogTitle>
          <DialogDescription>{request?.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => setRequest(null)}>
            Cancel
          </Button>
          <Button
            variant={request?.destructive ? "destructive" : "default"}
            disabled={pending}
            onClick={async () => {
              if (!request) return;
              setPending(true);
              try {
                await request.action();
                setRequest(null);
              } catch {
                // The mutation already showed why; keep the dialog so it can be retried.
              } finally {
                setPending(false);
              }
            }}
          >
            {pending && <Loader2Icon className="animate-spin" />}
            {request?.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
  return [setRequest, dialog];
}
