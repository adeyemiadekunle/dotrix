// Gr8r's files (gr8r-studio/src/views/files.js): search, type, sort, grid or list, drop to upload.
// dotrix: documents are also converted to Markdown into the project's knowledge, for the agents.
import type { CSSProperties } from "react";

import { openPop, openTask } from "../core/actions";
import { Ic } from "../core/icons";
import { previewFile } from "../core/more";
import { ago } from "../core/utils";
import { D, S, mem, render, task } from "../data/store";
import { handleFiles, uploads } from "../overlays/Drawer";
import { Av, Empty, FT, FilePrev, fileType } from "../ui/helpers";

const css = (o: Record<string, string | number>) => o as CSSProperties;
const set = (k: "fileQ" | "fileType" | "fileSort", v: string) => {
  S.ui[k] = v;
  render();
};

export function Files({ pid }: { pid: string }) {
  const u = S.ui;
  const q = u.fileQ.toLowerCase();
  const ft = u.fileType;
  const sort = u.fileSort;
  const fs = D().files.filter((f) => f.project === pid && (!q || f.name.toLowerCase().includes(q)) && (ft === "all" || f.type === ft));
  fs.sort((a, b) => (sort === "name" ? a.name.localeCompare(b.name) : sort === "type" ? a.type.localeCompare(b.type) : b.at - a.at));
  const ups = uploads.filter((x) => x.project === pid);
  const view = u.fileView;
  const filtered = Boolean(q) || ft !== "all";
  return (
    <>
      <div className="toolbar">
        <div className="inwrap">
          <Ic n="search" s={13} />
          <input className="input search-sm" placeholder="Search files" value={u.fileQ} onChange={(e) => set("fileQ", e.target.value)} aria-label="Search files" />
        </div>
        <select className="select" style={{ height: 26, width: "auto", fontSize: 12 }} value={ft} onChange={(e) => set("fileType", e.target.value)} aria-label="Filter by type">
          <option value="all">All types</option>
          {Object.entries(FT)
            .filter(([k]) => k !== "other")
            .map(([k, v]) => (
              <option key={k} value={k}>
                {v.n}
              </option>
            ))}
        </select>
        <select className="select" style={{ height: 26, width: "auto", fontSize: 12 }} value={sort} onChange={(e) => set("fileSort", e.target.value)} aria-label="Sort">
          {[
            ["date", "Newest"],
            ["name", "Name"],
            ["type", "Type"],
          ].map(([k, n]) => (
            <option key={k} value={k}>
              Sort: {n}
            </option>
          ))}
        </select>
        <span className="sp" />
        <div className="seg">
          {(
            [
              ["grid", "layout-grid"],
              ["list", "list"],
            ] as const
          ).map(([k, i]) => (
            <button key={k} className={view === k ? "on" : ""} onClick={() => ((u.fileView = k), render())} aria-label={`${k} view`}>
              <Ic n={i} s={13} />
            </button>
          ))}
        </div>
        <label className="btn btn-primary btn-sm" style={{ cursor: "pointer" }}>
          <Ic n="upload" s={13} />
          Upload
          <input type="file" multiple hidden onChange={(e) => handleFiles(e.target.files, { project: pid })} />
        </label>
      </div>
      <div className="page wide" style={{ paddingTop: 16 }}>
        <label className="dropzone" data-dropzone={pid} style={{ marginBottom: 16 }}>
          <Ic n="upload-cloud" s={18} />
          <span>
            Drop files here or <span className="link">browse</span> — documents are also converted for the agents to read
          </span>
          <input type="file" multiple hidden onChange={(e) => handleFiles(e.target.files, { project: pid })} />
        </label>
        {ups.length > 0 && (
          <div className="col" style={{ gap: 6, marginBottom: 16 }}>
            {ups.map((x) => (
              <div key={x.id} className="upl">
                <span className="ftype" style={css({ "--c": FT[fileType(x.name)]!.c })}>
                  <Ic n={FT[fileType(x.name)]!.i} s={14} />
                </span>
                <div className="grow">
                  <div className="row">
                    <span className="trunc" style={{ fontWeight: 500 }}>
                      {x.name}
                    </span>
                    <span className="sp" />
                    <span className="faint num" style={{ fontSize: 11.5 }}>
                      {x.pct}%
                    </span>
                  </div>
                  <div className="prog" style={{ marginTop: 6 }}>
                    <i style={css({ "--p": x.pct / 100 })} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {!fs.length ? (
          <Empty
            icon={filtered ? "search-x" : "folder-open"}
            title={filtered ? "No results found" : "No files yet"}
            text={filtered ? "No files match your search." : "Upload designs, documents, and assets to share them with the project."}
          />
        ) : view === "grid" ? (
          <div className="fgrid">
            {fs.map((f) => (
              <div
                key={f.id}
                className="fcard"
                onClick={() => previewFile(f.id)}
                onContextMenu={(e) => (e.preventDefault(), openPop(e.currentTarget, "ctx", { ctx: "file", id: f.id, x: e.clientX, y: e.clientY }))}
                role="button"
                tabIndex={0}
              >
                <FilePrev f={f} />
                <div className="fi">
                  <span className="fn trunc">{f.name}</span>
                  <span className="fm">
                    {f.size} · {mem(f.by)?.name.split(" ")[0]} · {ago(f.at)}
                  </span>
                </div>
                <button className="ibtn ibtn-xs more" onClick={(e) => (e.stopPropagation(), openPop(e.currentTarget, "ctx", { ctx: "file", id: f.id }))} aria-label="File options">
                  <Ic n="ellipsis" s={13} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="panel" style={{ overflowX: "auto" }}>
            <table className="perm-t" style={{ minWidth: 680 }}>
              <thead>
                <tr>
                  <th style={{ paddingLeft: 14 }}>Name</th>
                  <th style={{ textAlign: "left" }}>Type</th>
                  <th style={{ textAlign: "left" }}>Size</th>
                  <th style={{ textAlign: "left" }}>Uploaded by</th>
                  <th style={{ textAlign: "left" }}>Date</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {fs.map((f) => (
                  <tr key={f.id}>
                    <td style={{ paddingLeft: 14 }}>
                      <span className="row">
                        <span className="ftype" style={css({ "--c": FT[f.type]!.c })}>
                          <Ic n={FT[f.type]!.i} s={14} />
                        </span>
                        <span style={{ fontWeight: 500 }}>{f.name}</span>
                        {f.task && task(f.task) && (
                          <button className="badge" onClick={() => openTask(f.task!)}>
                            <Ic n="link" s={10} />
                            {task(f.task)!.key}
                          </button>
                        )}
                      </span>
                    </td>
                    <td style={{ textAlign: "left" }} className="muted">
                      {FT[f.type]!.n}
                    </td>
                    <td style={{ textAlign: "left" }} className="num muted">
                      {f.size}
                    </td>
                    <td style={{ textAlign: "left" }}>
                      <span className="row">
                        <Av id={f.by} cls="sm" tip={false} />
                        {mem(f.by)?.name}
                      </span>
                    </td>
                    <td style={{ textAlign: "left" }} className="muted">
                      {ago(f.at)}
                    </td>
                    <td>
                      <button className="ibtn ibtn-sm" onClick={(e) => openPop(e.currentTarget, "ctx", { ctx: "file", id: f.id })} aria-label="File options">
                        <Ic n="ellipsis" s={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
