// What Kai did in a coding session, for the panel beside its conversation (screens/Chat.tsx): the latest
// turn's changes, every file the session changed (by folder, with the turn that last changed it), and the
// commands it ran (its `tool` events that start "Ran ").

interface TurnLike {
  turn: number;
  files_changed?: Record<string, unknown>[] | null;
  events?: { kind: string; text: string; at: string }[] | null;
}
interface Changed {
  path: string;
  added: number;
  removed: number;
  turn: number;
}
interface KaiWork {
  latest: Changed[];
  folders: [string, Changed[]][];
  files: number;
  commands: { turn: number; at: string; text: string }[];
}

const pathOf = (f: Record<string, unknown>) => String(f.path ?? f.file ?? f.name ?? "");

export function kaiWork(turns: TurnLike[]): KaiWork {
  const changed = (f: Record<string, unknown>, turn: number): Changed => ({
    path: pathOf(f),
    added: Number(f.added ?? 0),
    removed: Number(f.removed ?? 0),
    turn,
  });
  const last = turns.at(-1);
  const every = new Map<string, Changed>();
  for (const t of turns) for (const f of t.files_changed ?? []) every.set(pathOf(f), changed(f, t.turn));
  const folders = new Map<string, Changed[]>();
  for (const f of [...every.values()].sort((a, b) => a.path.localeCompare(b.path))) {
    const folder = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ".";
    folders.set(folder, [...(folders.get(folder) ?? []), f]);
  }
  return {
    latest: (last?.files_changed ?? []).map((f) => changed(f, last!.turn)),
    folders: [...folders],
    files: every.size,
    commands: turns.flatMap((t) =>
      (t.events ?? []).filter((e) => e.kind === "tool" && e.text.startsWith("Ran ")).map((e) => ({ turn: t.turn, at: e.at, text: e.text.slice(4) })),
    ),
  };
}
