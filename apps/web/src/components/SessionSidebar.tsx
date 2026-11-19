import { createContext, useContext, useEffect, useState } from "react";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { go } from "../core/nav";
import { Ic } from "../core/icons";
import { useStoredFlag } from "../ui/splitter";

export function useSessionSidebar(area: "chat" | "coding", selection: string, autoHide = false) {
  const [savedHidden, setSavedHidden] = useStoredFlag(`dotrix.${area}.listMin`);
  const [narrow, setNarrow] = useState(() => window.matchMedia("(max-width: 900px)").matches);
  const [listOpen, setListOpen] = useState(false);
  const [keepOpen, setKeepOpen] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const update = () => setNarrow(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => setListOpen(false), [selection]);
  useEffect(() => setKeepOpen(false), [autoHide]);
  const hidden = narrow ? Boolean(selection) && !listOpen : savedHidden || (autoHide && !keepOpen);
  return {
    id: `${area}-session-list`,
    hidden,
    listOpen,
    closeList: () => setListOpen(false),
    toggle: () => {
      if (narrow) {
        if (!selection) go(area === "chat" ? "chat" : "codes", {}, { search: "new=1" });
        else setListOpen(!listOpen);
      } else {
        setSavedHidden(!hidden);
        setKeepOpen(hidden);
      }
    },
  };
}

export const SessionSidebarContext = createContext<ReturnType<typeof useSessionSidebar> | null>(null);

/** The same panel icon hides the list and restores it beside the conversation. */
export function SessionListToggle() {
  const sidebar = useContext(SessionSidebarContext);
  if (!sidebar) return null;
  const label = sidebar.hidden ? "Show the list" : "Hide the list";
  return (
    <ActionButton
      className="ibtn session-list-toggle"
      onClick={() => {
        sidebar.toggle();
        requestAnimationFrame(() => {
          const buttons = document.querySelectorAll<HTMLButtonElement>(`button[aria-controls="${sidebar.id}"]`);
          [...buttons].find((button) => button.getClientRects().length > 0)?.focus();
        });
      }}
      aria-label={label}
      data-tip={label}
      aria-expanded={!sidebar.hidden}
      aria-controls={sidebar.id}
    >
      <Ic n="sidebar-simple" s={20} />
    </ActionButton>
  );
}
