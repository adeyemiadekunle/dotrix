import { CodeBlock } from "@dotrix/ui/components/code-block";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@dotrix/ui/components/dialog";
import { Link } from "@/lib/navigation";
import { Fragment, useEffect, useState } from "react";

/** "⌘" on a Mac, "Ctrl" elsewhere (decided after hydration, so the server's markup matches). */
function useModKey(): string {
  const [mod, setMod] = useState("Ctrl");
  useEffect(() => {
    if (/Mac|iPhone|iPad/.test(navigator.userAgent)) setMod("⌘");
  }, []);
  return mod;
}

/** Keys pressed together ("Ctrl + K"), or either of them with `or` ("↑ or ↓"). */
function Keys({ keys, or = false }: { keys: string[]; or?: boolean }) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      {keys.map((key, i) => (
        <Fragment key={key}>
          {i > 0 && <span className="text-muted-foreground text-xs">{or ? "or" : "+"}</span>}
          <kbd className="bg-muted min-w-6 rounded border px-1.5 py-0.5 text-center font-mono text-xs">{key}</kbd>
        </Fragment>
      ))}
    </span>
  );
}

/** Every keyboard shortcut the app has, grouped by where it works. */
export function KeyboardShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const mod = useModKey();
  // [what it does, the keys, whether they're alternatives rather than a combination]
  const groups: { title: string; items: [string, string[], boolean?][] }[] = [
    {
      title: "Anywhere",
      items: [
        ["Search, and go to any issue, document, project, or page", [mod, "K"]],
        ["Show or hide the sidebar", [mod, "B"]],
      ],
    },
    {
      title: "Search",
      items: [
        ["Move through the results", ["↑", "↓"], true],
        ["Open the result", ["Enter"]],
      ],
    },
    {
      title: "Chat and comments",
      items: [
        ["Send a message", ["Enter"]],
        ["New line in a message", ["Shift", "Enter"]],
        ["Post a comment on an issue", [mod, "Enter"]],
      ],
    },
    {
      title: "Board",
      items: [
        ["Pick up a card, and drop it", ["Space"]],
        ["Move it up or down in its column", ["↑", "↓"], true],
        ["Move it to the previous or next column", ["←", "→"], true],
        ["Put it back where it was", ["Esc"]],
      ],
    },
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Board shortcuts work on a card with keyboard focus, in Ranked order.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-5">
          {groups.map((group) => (
            <section key={group.title} className="grid gap-2">
              <h3 className="text-muted-foreground text-xs font-semibold tracking-wide uppercase">{group.title}</h3>
              <ul className="grid gap-2">
                {group.items.map(([label, keys, or]) => (
                  <li key={label} className="flex items-center justify-between gap-4 text-sm">
                    {label}
                    <Keys keys={keys} or={or} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const INSTALL = 'uv tool install "git+https://github.com/adeyemiadekunle/multi-agent-pm#subdirectory=apps/cli"';

/** How to install the `dotrix` CLI, sign it in, and link a checkout to a project here. */
export function ConnectCliDialog({
  open,
  onOpenChange,
  workspaceSlug,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceSlug: string | undefined;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Connect the CLI</DialogTitle>
          <DialogDescription>
            Use the agents and the board from your terminal, and from Claude Code or Codex.
          </DialogDescription>
        </DialogHeader>
        <ol className="grid gap-4 text-sm">
          <li className="grid gap-2">
            <span>
              <span className="font-medium">1. Install it</span> (Python 3.11 or newer and{" "}
              <a href="https://docs.astral.sh/uv/" target="_blank" rel="noreferrer" className="text-primary hover:underline">
                uv
              </a>
              ).
            </span>
            <CodeBlock code={INSTALL} language="bash" />
          </li>
          <li className="grid gap-2">
            <span>
              <span className="font-medium">2. Sign in.</span> It shows a code to confirm here in the browser.
            </span>
            <CodeBlock code="dotrix login" language="bash" />
          </li>
          <li className="grid gap-2">
            <span>
              <span className="font-medium">3. Link a checkout</span> to its project, found by its git remote.
              Or name the project: <code className="font-mono text-xs">dotrix link . --workspace {workspaceSlug ?? "<slug>"} --project KEY</code>.
            </span>
            <CodeBlock code="cd path/to/your/repo && dotrix connect" language="bash" />
          </li>
          <li className="grid gap-2">
            <span>
              <span className="font-medium">4. Then</span> chat with the agents and work the board.
            </span>
            <CodeBlock code={"dotrix chat\ndotrix issue list --mine"} language="bash" />
          </li>
        </ol>
        {workspaceSlug && (
          <p className="text-muted-foreground text-xs">
            Signed-in devices are listed in{" "}
            <Link href={`/w/${workspaceSlug}/settings/devices`} className="text-primary hover:underline" onClick={() => onOpenChange(false)}>
              Settings → Devices and tokens
            </Link>
            , where you can sign them out.
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
