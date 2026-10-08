// Gr8r's drag and drop (gr8r-studio/src/actions/drag-drop.js), as is: global listeners keyed on
// data attributes. Board cards between columns (data-drag-card, data-drop-col, data-col-body),
// list rows (a row's handle data-drag-row; the row data-task-row, data-group, data-lkey), calendar
// items onto days (data-drag-cal, data-drop-day), sidebar projects (data-drag-proj,
// data-proj-drop), files onto drop zones and the drawer (data-dropzone, data-dropzone-task), table
// column widths (data-rsz) and timeline bars (data-bar, data-dw).
import { PR, ST } from "./constants";
import { applyPatch, updateTask } from "./actions";
import { addD, diffD, fmtDate, iso, parse } from "./utils";
import { D, S, mutate, proj, render, save, task } from "../data/store";
import type { Task } from "../data/types";
import { viewOf } from "../shell/viewEngine";
import { handleFiles } from "../overlays/Drawer";
import { toast } from "../ui/toast";

type Drag = {
  type: "card" | "row" | "cal" | "proj";
  id: string;
  col?: string;
  before?: string | null;
  target?: string;
  pos?: "before" | "after";
  group?: string;
  lkey?: string;
  day?: string;
};
let DRAG: Drag | null = null;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const $$ = (s: string) => [...document.querySelectorAll<HTMLElement>(s)];
const closest = (e: Event, s: string) => (e.target as Element | null)?.closest?.<HTMLElement>(s) ?? null;

export function clearDropMarks() {
  $$(".drop-line").forEach((x) => x.remove());
  $$(".over").forEach((x) => x.classList.remove("over"));
  $$(".drop-before,.drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));
  $$(".dragging").forEach((x) => x.classList.remove("dragging"));
}

let installed = false;
export function installDragDrop() {
  if (installed) return;
  installed = true;
  document.addEventListener("dragstart", (e) => {
    const card = closest(e, "[data-drag-card]");
    const row = closest(e, "[data-drag-row]");
    const cal = closest(e, "[data-drag-cal]");
    const sp = closest(e, "[data-drag-proj]");
    const el = card || row || cal || sp;
    if (!el) return;
    DRAG = card
      ? { type: "card", id: card.dataset.dragCard! }
      : row
        ? { type: "row", id: row.dataset.dragRow! }
        : cal
          ? { type: "cal", id: cal.dataset.dragCal! }
          : { type: "proj", id: sp!.dataset.dragProj! };
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      try {
        e.dataTransfer.setData("text/plain", DRAG.id);
      } catch {
        /* not supported here */
      }
    }
    const vis = row ? row.closest<HTMLElement>(".trow")! : el;
    if (row)
      try {
        e.dataTransfer?.setDragImage(vis, 20, 18);
      } catch {
        /* not supported here */
      }
    S.ui.pop = null;
    setTimeout(() => vis.classList.add("dragging"), 0);
  });
  document.addEventListener("dragend", () => {
    DRAG = null;
    clearDropMarks();
  });
  document.addEventListener("dragover", (e) => {
    const hasFiles = e.dataTransfer && [...(e.dataTransfer.types || [])].includes("Files");
    if (hasFiles) {
      const dz = closest(e, "[data-dropzone],[data-dropzone-task],.drawer");
      if (dz) {
        e.preventDefault();
        $$(".dropzone.over").forEach((x) => x !== dz && x.classList.remove("over"));
        dz.classList.add("over");
      }
      return;
    }
    if (!DRAG) return;
    if (DRAG.type === "card") {
      const col = closest(e, "[data-drop-col]");
      if (!col) return;
      e.preventDefault();
      $$(".bcol.over").forEach((x) => x !== col && x.classList.remove("over"));
      col.classList.add("over");
      const body = col.querySelector<HTMLElement>("[data-col-body]");
      if (!body) return;
      const cards = [...body.querySelectorAll<HTMLElement>(".kcard:not(.dragging)")];
      const after = cards.find((c) => {
        const r = c.getBoundingClientRect();
        return e.clientY < r.top + r.height / 2;
      });
      let line = $(".drop-line");
      if (!line) {
        line = document.createElement("div");
        line.className = "drop-line";
      }
      const ref = after || body.querySelector(".addcard, .composer");
      if (line.nextSibling !== ref || line.parentNode !== body) body.insertBefore(line, ref);
      DRAG.col = col.dataset.dropCol;
      DRAG.before = after ? after.dataset.dragCard : null;
    } else if (DRAG.type === "row") {
      const row = closest(e, ".trow[data-task-row]");
      if (!row || row.dataset.taskRow === DRAG.id) return;
      e.preventDefault();
      const r = row.getBoundingClientRect();
      const before = e.clientY < r.top + r.height / 2;
      $$(".drop-before,.drop-after").forEach((x) => x.classList.remove("drop-before", "drop-after"));
      row.classList.add(before ? "drop-before" : "drop-after");
      DRAG.target = row.dataset.taskRow;
      DRAG.pos = before ? "before" : "after";
      DRAG.group = row.dataset.group;
      DRAG.lkey = row.dataset.lkey;
    } else if (DRAG.type === "cal") {
      const day = closest(e, "[data-drop-day]");
      if (!day) return;
      e.preventDefault();
      $$(".over").forEach((x) => x !== day && x.classList.remove("over"));
      day.classList.add("over");
      DRAG.day = day.dataset.dropDay;
    } else if (DRAG.type === "proj") {
      const it = closest(e, "[data-proj-drop]");
      if (!it) return;
      e.preventDefault();
      $$(".drop-before").forEach((x) => x.classList.remove("drop-before"));
      it.querySelector(".sitem")?.classList.add("drop-before");
      DRAG.before = it.dataset.projDrop;
    }
  });
  document.addEventListener("dragleave", (e) => {
    const dz = closest(e, ".dropzone");
    if (dz && !dz.contains(e.relatedTarget as Node)) dz.classList.remove("over");
  });
  document.addEventListener("drop", (e) => {
    const files = e.dataTransfer?.files;
    if (files && files.length && !DRAG) {
      const dz = closest(e, "[data-dropzone],[data-dropzone-task],.drawer");
      if (!dz) return;
      e.preventDefault();
      clearDropMarks();
      if (dz.dataset.dropzone) handleFiles(files, { project: dz.dataset.dropzone });
      else {
        const t = task(dz.dataset.dropzoneTask || S.ui.drawer);
        if (t) handleFiles(files, { project: t.project, task: t.id });
      }
      return;
    }
    if (!DRAG) return;
    e.preventDefault();
    const d = DRAG;
    DRAG = null;
    clearDropMarks();
    if (d.type === "card" && d.col) {
      const t = task(d.id)!;
      const colTs = D()
        .tasks.filter((x) => x.status === d.col && x.id !== t.id && !x.archived)
        .sort((a, b) => a.order - b.order);
      let order: number;
      if (d.before) {
        const i = colTs.findIndex((x) => x.id === d.before);
        const prev = colTs[i - 1];
        const nx = colTs[i]!;
        order = prev ? (prev.order + nx.order) / 2 : nx.order - 1;
      } else order = colTs.length ? colTs[colTs.length - 1]!.order + 1 : t.order;
      const moved = t.status !== d.col;
      mutate(() => {
        t.order = order;
        if (moved) applyPatch(t, { status: d.col as Task["status"] });
      });
      if (moved) toast(`Moved “${t.title}” to ${ST[d.col as Task["status"]].name}`, { ms: 2200 });
    } else if (d.type === "row" && d.target) {
      const t = task(d.id)!;
      const tg = task(d.target)!;
      const v = d.lkey ? viewOf(d.lkey) : null;
      const all = D()
        .tasks.filter((x) => !x.archived && x.id !== t.id)
        .sort((a, b) => a.order - b.order);
      const i = all.findIndex((x) => x.id === tg.id);
      const nb = d.pos === "before" ? all[i - 1] : all[i + 1];
      const order = nb ? (tg.order + nb.order) / 2 : tg.order + (d.pos === "before" ? -1 : 1);
      const patch: Partial<Task> = {};
      if (v && d.group) {
        const g = v.group;
        if (g === "status" && d.group in ST) patch.status = d.group as Task["status"];
        if (g === "priority" && d.group in PR) patch.priority = d.group as Task["priority"];
        if (g === "assignee") patch.assignee = d.group === "none" ? null : d.group;
        if (g === "project" && proj(d.group)) patch.project = d.group;
      }
      let switched = false;
      mutate(() => {
        t.order = order;
        applyPatch(t, patch);
        if (v && v.sort.f !== "manual") {
          v.sort = { f: "manual", dir: 1 };
          switched = true;
        }
      });
      if (switched) toast("Sorted manually to keep your order", { kind: "info", ms: 2200 });
    } else if (d.type === "cal" && d.day) {
      const t = task(d.id)!;
      if (t.due === d.day) return;
      const len = t.start && t.due ? diffD(parse(t.due)!, parse(t.start)!) : null;
      updateTask(t.id, { due: d.day, ...(len != null ? { start: iso(addD(parse(d.day)!, -len)) } : {}) });
      toast(`Rescheduled “${t.title}” to ${fmtDate(d.day)}`, { ms: 2200 });
    } else if (d.type === "proj" && d.before && d.before !== d.id) {
      const o = D().projOrder.filter((x) => x !== d.id);
      o.splice(o.indexOf(d.before), 0, d.id);
      D().projOrder = o;
      save();
      render();
    }
  });

  /* timeline bar drag + table column resize (pointer events) */
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const rz = closest(e, "[data-rsz]");
    if (rz) {
      e.preventDefault();
      e.stopPropagation();
      const c = rz.dataset.rsz!;
      const v = viewOf(rz.dataset.key!);
      const tbl = rz.closest("table")!;
      const col = tbl.querySelector<HTMLElement>(`col[data-col="${c}"]`)!;
      const w0 = col.getBoundingClientRect().width || parseFloat(col.style.width);
      const tw0 = tbl.getBoundingClientRect().width;
      const x0 = e.clientX;
      rz.classList.add("on");
      const mv = (ev: PointerEvent) => {
        const w = Math.max(64, w0 + ev.clientX - x0);
        col.style.width = w + "px";
        tbl.style.width = tw0 + w - w0 + "px";
      };
      const up = (ev: PointerEvent) => {
        removeEventListener("pointermove", mv);
        removeEventListener("pointerup", up);
        v.colW[c] = Math.max(64, Math.round(w0 + ev.clientX - x0));
        save();
        render();
      };
      addEventListener("pointermove", mv);
      addEventListener("pointerup", up);
      return;
    }
    const b = closest(e, "[data-bar]");
    if (!b) return;
    const x0 = e.clientX;
    const l0 = parseFloat(b.style.left);
    const dw = +b.dataset.dw!;
    let moved = false;
    const mv = (ev: PointerEvent) => {
      const dx = ev.clientX - x0;
      if (Math.abs(dx) > 4) {
        moved = true;
        b.classList.add("dragging");
      }
      if (moved) b.style.left = l0 + Math.round(dx / dw) * dw + "px";
    };
    const up = (ev: PointerEvent) => {
      removeEventListener("pointermove", mv);
      removeEventListener("pointerup", up);
      if (!moved) return;
      suppressClick = true;
      setTimeout(() => (suppressClick = false), 60);
      const days = Math.round((ev.clientX - x0) / dw);
      const t = task(b.dataset.bar)!;
      if (!days) return render();
      updateTask(t.id, { due: iso(addD(parse(t.due)!, days)), start: t.start ? iso(addD(parse(t.start)!, days)) : null });
      toast(`Moved “${t.title}” ${Math.abs(days)} day${Math.abs(days) > 1 ? "s" : ""} ${days > 0 ? "later" : "earlier"}`, { ms: 2200 });
    };
    addEventListener("pointermove", mv);
    addEventListener("pointerup", up);
  });
}
/** A timeline bar that was just dragged shouldn't also open its task. */
export let suppressClick = false;
