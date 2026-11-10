// Drag and drop: global listeners keyed on data attributes. Board cards between columns
// (data-drag-card, data-drop-col, data-col-body), list rows (a row's handle data-drag-row; the row
// data-task-row, data-group, data-lkey), sidebar projects (data-drag-proj, data-proj-drop), and
// files onto drop zones and the drawer (data-dropzone, data-dropzone-task).
import { PR, ST } from "./constants";
import { applyPatch } from "./actions";
import { isLive, taskRanked } from "../data/live";
import { D, S, mutate, proj, render, save, task } from "../data/store";
import type { Task } from "../data/types";
import { viewOf } from "../shell/viewEngine";
import { handleFiles } from "../overlays/Drawer";
import { toast } from "../ui/toast";
type Drag = {
  type: "card" | "row" | "proj";
  id: string;
  col?: string;
  before?: string | null;
  target?: string;
  pos?: "before" | "after";
  group?: string;
  lkey?: string;
};
let DRAG: Drag | null = null;
const $ = <T extends Element = HTMLElement>(s: string) => document.querySelector<T>(s);
const $$ = (s: string) => [...document.querySelectorAll<HTMLElement>(s)];
const closest = (e: Event, s: string) => (e.target as Element | null)?.closest?.<HTMLElement>(s) ?? null;
function clearDropMarks() {
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
    const sp = closest(e, "[data-drag-proj]");
    const el = card || row || sp;
    if (!el) return;
    DRAG = card ? { type: "card", id: card.dataset.dragCard! } : row ? { type: "row", id: row.dataset.dragRow! } : { type: "proj", id: sp!.dataset.dragProj! };
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
      // A real workspace shows the new place and column through the saves (the cache); the sample edits the task.
      mutate(() => {
        if (!isLive()) t.order = order;
        if (moved) applyPatch(t, { status: d.col as Task["status"] });
      });
      // The API's rank is per project: place it by its neighbour there.
      const sameProject = colTs.filter((x) => x.project === t.project);
      const before = d.before ? task(d.before) : undefined;
      if (before?.project === t.project) taskRanked(t, before, undefined, order);
      else if (!d.before && sameProject.length) taskRanked(t, undefined, sameProject[sameProject.length - 1], order);
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
        if (!isLive()) t.order = order;
        applyPatch(t, patch);
        if (v && v.sort.f !== "manual") {
          v.sort = { f: "manual", dir: 1 };
          switched = true;
        }
      });
      if (tg.project === t.project) taskRanked(t, d.pos === "before" ? tg : undefined, d.pos === "after" ? tg : undefined, order);
      if (switched) toast("Sorted manually to keep your order", { kind: "info", ms: 2200 });
    } else if (d.type === "proj" && d.before && d.before !== d.id) {
      const o = D().projOrder.filter((x) => x !== d.id);
      o.splice(o.indexOf(d.before), 0, d.id);
      D().projOrder = o;
      save();
      render();
    }
  });
}
