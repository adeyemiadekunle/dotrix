// How a workspace's upload storage reads in Settings: "312 MB of 1 GB used", a bar that turns to
// the warning tone at 80% and the danger tone at 100%. Sizes are decimal, like the API's limits.

type StorageTone = "ok" | "warn" | "full";

export interface StorageLine {
  text: string;
  /** 0..1 of the limit; null without one. */
  ratio: number | null;
  tone: StorageTone;
  /** Shown under a full workspace's bar. */
  note: string | null;
}

export function formatBytes(n: number): string {
  if (n >= 1_000_000_000) return `${trim(n / 1_000_000_000)} GB`;
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)} MB`;
  if (n >= 1_000) return `${Math.round(n / 1_000)} KB`;
  return `${n} B`;
}

const trim = (x: number) => String(Math.round(x * 10) / 10);

export function storageLine(used: number, limit: number | null): StorageLine {
  if (limit === null) return { text: `Storage: ${formatBytes(used)} used`, ratio: null, tone: "ok", note: null };
  const ratio = limit > 0 ? Math.min(used / limit, 1) : 1;
  const tone: StorageTone = used >= limit ? "full" : ratio >= 0.8 ? "warn" : "ok";
  return {
    text: `Storage: ${formatBytes(used)} of ${formatBytes(limit)} used`,
    ratio,
    tone,
    note: tone === "full" ? "Uploads are paused until you delete files or the limit is raised." : null,
  };
}
