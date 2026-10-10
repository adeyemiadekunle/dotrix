// Gr8r's keyboard (gr8r-studio/src/actions/keyboard.js): ⌘K, ⌘⇧L, focus kept inside modals,
// arrows in menus and the palette, Escape closing the top surface, and single-key shortcuts
// (G then a letter to go somewhere, / to search, N, P, ?, [, E).
import { STATUSES } from "./constants";
import { closeDrawer, closePop, toggleSide, updateTask } from "./actions";
import { cancelComposer, closeModal, editTask, newProject, newTask, shortcuts } from "./more";
import { go, type Route } from "./nav";
import { S, render } from "../data/store";
import { closePalette, openPalette, palMove, palRun, toggleDark } from "../overlays/Palette";

let gPending = 0;
let installed = false;

export function installKeyboard() {
  if (installed) return;
  installed = true;
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    const t = e.target as HTMLElement;
    const typing = t.matches?.('input, textarea, select, [contenteditable="true"]');
    const pl = S.ui.palette;
    if (mod && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (pl) closePalette();
      else openPalette();
      return;
    }
    if (mod && e.shiftKey && e.key.toLowerCase() === "l") {
      e.preventDefault();
      toggleDark();
      return;
    }
    // Keep Tab inside whichever surface is modal right now.
    if (e.key === "Tab" && !pl) {
      const box = S.ui.modals.length
        ? [...document.querySelectorAll<HTMLElement>(".modal")].pop()
        : S.ui.drawer && S.ui.drawerFull
          ? document.querySelector<HTMLElement>(".drawer")
          : null;
      if (box) {
        const f = [
          ...box.querySelectorAll<HTMLElement>(
            'a[href],button:not([disabled]),input:not([type=hidden]):not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"]),[contenteditable="true"]',
          ),
        ].filter((x) => x.offsetParent !== null);
        if (f.length) {
          const i = f.indexOf(document.activeElement as HTMLElement);
          if (e.shiftKey && i <= 0) {
            e.preventDefault();
            f[f.length - 1]!.focus();
            return;
          }
          if (!e.shiftKey && (i === f.length - 1 || i === -1)) {
            e.preventDefault();
            f[0]!.focus();
            return;
          }
        }
      }
    }
    // Arrow keys move through open menus and pickers.
    if (S.ui.pop && !pl && ["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      const items = [...document.querySelectorAll<HTMLElement>(".pop.floating .mi:not(:disabled), .pop.floating .valbtn")].filter(
        (x) => x.offsetParent !== null,
      );
      if (items.length) {
        e.preventDefault();
        const i = items.indexOf(document.activeElement as HTMLElement);
        const n =
          e.key === "Home" ? 0 : e.key === "End" ? items.length - 1 : e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
        items[n]!.focus();
        return;
      }
    }
    if (pl) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        palMove(e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Enter") {
        e.preventDefault();
        palRun();
      } else if (e.key === "Escape") {
        e.preventDefault();
        closePalette();
      } else if (e.key === "Tab") {
        e.preventDefault();
        pl.mode = pl.mode === "cmd" ? "search" : "cmd";
        pl.hl = 0;
        render();
      } else if (e.key === "Backspace" && !pl.q && pl.mode !== "cmd") {
        e.preventDefault();
        pl.mode = "cmd";
        render();
      }
      return;
    }
    if (e.key === "Escape") {
      if (S.ui.pop) return closePop();
      if (S.ui.mention) return ((S.ui.mention = null), render());
      if (S.ui.editCell) return ((S.ui.editCell = null), render());
      if (S.ui.composer) return cancelComposer();
      if (S.ui.modals.length) return closeModal();
      if (S.ui.subOpen) {
        if (typing) t.blur();
        S.ui.subOpen = null;
        return render();
      }
      if (S.ui.drawer) {
        if (typing) t.blur();
        return closeDrawer();
      }
      if (S.ui.mnav) return ((S.ui.mnav = false), render());
      if (S.ui.sel.size) return (S.ui.sel.clear(), render());
      if (typing) t.blur();
      return;
    }
    if ((e.key === "Enter" || e.key === " ") && t.matches?.('[role="button"], [role="link"]') && t.tagName !== "BUTTON" && !typing) {
      e.preventDefault();
      t.click();
      return;
    }
    if (typing || mod || e.altKey) return;
    // number keys inside the status popover
    const pop = S.ui.pop;
    if (pop?.type === "status" && /^[1-6]$/.test(e.key) && typeof pop.id === "string") {
      const st = STATUSES[+e.key - 1];
      if (st) {
        closePop();
        updateTask(pop.id, { status: st.id });
      }
      return;
    }
    const k = e.key;
    if (gPending && Date.now() - gPending < 1200) {
      gPending = 0;
      const map: Record<string, Route> = {
        h: "home",
        t: "mytasks",
        p: "projects",
        i: "inbox",
        c: "calendar",
        s: "settings",
        n: "notifications",
        a: "chat",
        m: "members",
      };
      const r = map[k.toLowerCase()];
      if (r) {
        e.preventDefault();
        go(r);
      }
      return;
    }
    if (S.ui.modals.length) return;
    if (k === "g" || k === "G") {
      gPending = Date.now();
      return;
    }
    if (k === "/") {
      e.preventDefault();
      openPalette("search");
    } else if (k === "n" || k === "N") {
      e.preventDefault();
      newTask();
    } else if (k === "p" || k === "P") {
      e.preventDefault();
      newProject();
    } else if (k === "?") {
      e.preventDefault();
      shortcuts();
    } else if (k === "[") {
      e.preventDefault();
      toggleSide();
    } else if ((k === "e" || k === "E") && S.ui.drawer) {
      e.preventDefault();
      editTask(S.ui.drawer);
    }
  });
}
