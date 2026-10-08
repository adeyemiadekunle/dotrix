import { cn } from "@pmagent/ui/lib/utils";
import { useCallback, useMemo, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import { UserAvatar } from "@/components/user-avatar";
import { useMembers } from "@/lib/issues";
import { useMemberAvatarSrc, type Member } from "@/lib/profile";
import { useMe } from "@/lib/queries";

const MAX_SHOWN = 6;

/** The people who can see a project: whom a comment or chat message there can @mention. */
export function useMentionable(workspaceId: string | undefined, projectId: string | undefined): Member[] {
  const members = useMembers(workspaceId);
  const me = useMe();
  return useMemo(
    () =>
      (members.data ?? []).filter(
        (m) =>
          m.role !== "guest" &&
          m.user_id !== me.data?.id &&
          (m.sees_all_projects || (projectId !== undefined && m.project_ids.includes(projectId))),
      ),
    [members.data, me.data?.id, projectId],
  );
}

/** "@que" just before the caret (at the start or after a space), or null. */
function queryAt(text: string, caret: number): { start: number; query: string } | null {
  const match = /(^|\s)@([^\s@]{0,30})$/.exec(text.slice(0, caret));
  return match ? { start: caret - match[2]!.length - 1, query: match[2]!.toLowerCase() } : null;
}

/**
 * @mentions for a text box: typing "@" offers the people listed; picking one writes "@Name". The
 * box's text stays plain; `mentioned(text)` gives the ids of the people picked whose "@Name" is
 * still in it, for the API to notify.
 */
export function useMentions({
  people,
  value,
  onValueChange,
  inputRef,
}: {
  people: Member[];
  value: string;
  onValueChange: (value: string) => void;
  inputRef: RefObject<HTMLTextAreaElement | null>;
}) {
  const [open, setOpen] = useState<{ start: number; query: string } | null>(null);
  const [active, setActive] = useState(0);
  const picked = useRef(new Map<string, string>());

  const matches = useMemo(() => {
    if (!open) return [];
    // Any word of the name: "@lov" finds Ada Lovelace.
    return people
      .filter((m) => m.display_name.toLowerCase().split(/\s+/).some((word) => word.startsWith(open.query)))
      .slice(0, MAX_SHOWN);
  }, [open, people]);

  /** Call with the box's new text, after each change, to follow what's typed before the caret. */
  const track = useCallback((text: string, caret: number | null) => {
    const found = caret === null ? null : queryAt(text, caret);
    setOpen(found);
    setActive(0);
  }, []);

  function pick(member: Member) {
    if (!open) return;
    const end = open.start + 1 + open.query.length;
    const inserted = `@${member.display_name} `;
    const next = value.slice(0, open.start) + inserted + value.slice(end);
    picked.current.set(member.user_id, member.display_name);
    onValueChange(next);
    setOpen(null);
    const caret = open.start + inserted.length;
    requestAnimationFrame(() => {
      const box = inputRef.current;
      if (box) {
        box.focus();
        box.setSelectionRange(caret, caret);
      }
    });
  }

  /** Arrow keys, Enter, and Tab work the list while it's open; returns whether it took the key. */
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): boolean {
    if (!open || matches.length === 0) return false;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((i) => (i + step + matches.length) % matches.length);
      return true;
    }
    if ((event.key === "Enter" || event.key === "Tab") && !event.shiftKey) {
      event.preventDefault();
      pick(matches[active]!);
      return true;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(null);
      return true;
    }
    return false;
  }

  /** The ids of the people picked whose "@Name" is still in the text. */
  function mentioned(text: string): string[] {
    return [...picked.current].filter(([, name]) => text.includes(`@${name}`)).map(([id]) => id);
  }

  function reset() {
    picked.current.clear();
    setOpen(null);
  }

  const list =
    open && matches.length > 0 ? (
      <MentionList matches={matches} active={active} onPick={pick} onHover={setActive} />
    ) : null;

  return { list, track, onKeyDown, mentioned, reset };
}

function MentionOption({
  member,
  active,
  onPick,
  onHover,
}: {
  member: Member;
  active: boolean;
  onPick: () => void;
  onHover: () => void;
}) {
  return (
    <li
      role="option"
      aria-selected={active}
      // Keep the text box focused: pick on mouse down, before it would blur.
      onMouseDown={(e) => {
        e.preventDefault();
        onPick();
      }}
      onMouseMove={onHover}
      className={cn("flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm", active && "bg-muted")}
    >
      <UserAvatar name={member.display_name} src={useMemberAvatarSrc(member)} className="size-5 text-[9px]" />
      <span className="truncate">{member.display_name}</span>
      {member.title && <span className="text-muted-foreground ml-auto truncate text-xs">{member.title}</span>}
    </li>
  );
}

/** The people matching what's typed after "@", above the text box (its parent is `relative`). */
function MentionList({
  matches,
  active,
  onPick,
  onHover,
}: {
  matches: Member[];
  active: number;
  onPick: (member: Member) => void;
  onHover: (index: number) => void;
}) {
  return (
    <ul
      role="listbox"
      aria-label="Mention someone"
      className="bg-popover text-popover-foreground absolute bottom-full left-0 z-20 mb-1 w-64 rounded-lg border p-1 shadow-md"
    >
      {matches.map((member, index) => (
        <MentionOption
          key={member.user_id}
          member={member}
          active={index === active}
          onPick={() => onPick(member)}
          onHover={() => onHover(index)}
        />
      ))}
    </ul>
  );
}
