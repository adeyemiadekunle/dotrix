import { Button } from "@dotrix/ui/components/button";
import { cn } from "@dotrix/ui/lib/utils";
import { CircleAlertIcon, CircleCheckIcon, FileTextIcon, Loader2Icon, UploadIcon, XIcon } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { DOCUMENT_EXTENSIONS, MAX_UPLOAD_MB, checkFile, formatBytes, type UploadState } from "@/lib/documents";

/** Drop files or pick them; files the backend can't import are rejected here with the reason. */
export function Dropzone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [rejected, setRejected] = useState<{ name: string; reason: string }[]>([]);

  function take(list: FileList | null) {
    const files = [...(list ?? [])];
    const bad = files.flatMap((f) => {
      const reason = checkFile(f);
      return reason ? [{ name: f.name, reason }] : [];
    });
    setRejected(bad);
    const good = files.filter((f) => !checkFile(f));
    if (good.length) onFiles(good);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    if (!disabled) take(event.dataTransfer.files);
  }

  return (
    <div className="grid gap-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center transition-colors",
          over && "border-primary bg-muted/60",
          disabled && "opacity-60",
        )}
      >
        <UploadIcon className="text-muted-foreground size-6" />
        <p className="text-sm">
          Drop specs, PRDs, or notes here, or{" "}
          <Button
            type="button"
            variant="link"
            className="h-auto p-0"
            disabled={disabled}
            onClick={() => input.current?.click()}
          >
            choose files
          </Button>
        </p>
        <p className="text-muted-foreground text-xs">
          PDF, Word, PowerPoint, Excel, HTML, CSV, JSON, XML, Markdown, or text · up to {MAX_UPLOAD_MB} MB each
        </p>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept={DOCUMENT_EXTENSIONS.join(",")}
          onChange={(e) => {
            take(e.target.files);
            e.target.value = ""; // allow picking the same file again
          }}
        />
      </div>
      {rejected.map((r) => (
        <p key={r.name} className="text-destructive flex items-center gap-1.5 text-xs">
          <CircleAlertIcon className="size-3.5" />
          {r.name}: {r.reason}
        </p>
      ))}
    </div>
  );
}

/** Files picked but not yet uploaded, removable. */
export function QueuedFiles({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  if (files.length === 0) return null;
  return (
    <ul className="divide-y rounded-md border text-sm">
      {files.map((file, i) => (
        <li key={`${file.name}-${i}`} className="flex items-center gap-2 px-3 py-2">
          <FileTextIcon className="text-muted-foreground size-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate">{file.name}</span>
          <span className="text-muted-foreground text-xs">{formatBytes(file.size)}</span>
          <Button type="button" size="icon" variant="ghost" className="size-7" onClick={() => onRemove(i)} aria-label={`Remove ${file.name}`}>
            <XIcon />
          </Button>
        </li>
      ))}
    </ul>
  );
}

/** Progress of an upload batch, one row per file. */
export function UploadProgress({ uploads }: { uploads: UploadState[] }) {
  if (uploads.length === 0) return null;
  return (
    <ul className="divide-y rounded-md border text-sm">
      {uploads.map((u, i) => (
        <li key={`${u.file.name}-${i}`} className="flex items-center gap-2 px-3 py-2">
          {u.status === "done" && <CircleCheckIcon className="size-4 shrink-0 text-emerald-600" />}
          {u.status === "error" && <CircleAlertIcon className="text-destructive size-4 shrink-0" />}
          {u.status === "uploading" && <Loader2Icon className="text-muted-foreground size-4 shrink-0 animate-spin" />}
          {u.status === "queued" && <FileTextIcon className="text-muted-foreground size-4 shrink-0" />}
          <span className="min-w-0 flex-1 truncate">{u.file.name}</span>
          <span className={cn("text-xs", u.status === "error" ? "text-destructive" : "text-muted-foreground")}>
            {u.status === "uploading"
              ? "Converting…"
              : u.status === "done"
                ? "Added"
                : u.status === "error"
                  ? u.error
                  : "Waiting"}
          </span>
        </li>
      ))}
    </ul>
  );
}
