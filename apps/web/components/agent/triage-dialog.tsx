import { Button } from "@pmagent/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@pmagent/ui/components/dialog";
import { Label } from "@pmagent/ui/components/label";
import { Textarea } from "@pmagent/ui/components/textarea";
import { useState, type FormEvent } from "react";

import { SubmitButton } from "@/components/form";
import { useTriage } from "@/lib/agent";
import type { Scope } from "@/lib/issues";

import { useChat } from "./chat-context";

/** Paste a bug report or request as it came in; the Project Manager checks for duplicates and
 * proposes the issue (or a comment on the existing one), which waits for approval. */
export function TriageDialog({
  scope,
  open,
  onOpenChange,
}: {
  scope: Scope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const triage = useTriage(scope);
  const chat = useChat();
  const [report, setReport] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <form
          className="grid gap-4"
          onSubmit={async (e: FormEvent) => {
            e.preventDefault();
            const run = await triage.mutateAsync(report.trim()).catch(() => null);
            if (run) {
              onOpenChange(false);
              setReport("");
              chat.show(run.thread_id);
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Triage a report</DialogTitle>
            <DialogDescription>
              Paste a bug report or request as it came in. The agents look for duplicates, then propose the issue
              with its type and priority, or a comment on the one that exists. Nothing changes until it&apos;s approved.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="triage-report">Report</Label>
            <Textarea
              id="triage-report"
              value={report}
              onChange={(e) => setReport(e.target.value)}
              placeholder="Drivers see the wrong delivery zone after switching depots…"
              rows={8}
              maxLength={10000}
              required
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <SubmitButton pending={triage.isPending}>Triage</SubmitButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
