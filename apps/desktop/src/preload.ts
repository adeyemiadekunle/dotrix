// Bridge between the web UI and native features (the web's core/desktop.ts): runners, worktrees, the
// app's version and What's new, updates, system notifications, and the Browser pane's profile. Expose only narrow, explicit APIs. The main process
// checks each call comes from the app's own page (main.ts, `handle`), and the worktree calls reach
// only folders inside ~/.dotrix/worktrees (runner.ts, `ownWorktree`).
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("dotrixDesktop", {
  platform: process.platform,
  runners: {
    list: () => ipcRenderer.invoke("dotrix:runners:list"),
    add: (workspace: string, projectKey: string) => ipcRenderer.invoke("dotrix:runners:add", workspace, projectKey),
    remove: (folder: string) => ipcRenderer.invoke("dotrix:runners:remove", folder),
    restart: (folder: string) => ipcRenderer.invoke("dotrix:runners:restart", folder),
    signIn: () => ipcRenderer.invoke("dotrix:runners:sign-in"),
    onChange: (listener: (runners: unknown[]) => void) => {
      const wrapped = (_event: unknown, runners: unknown[]) => listener(runners);
      ipcRenderer.on("dotrix:runners", wrapped);
      return () => ipcRenderer.removeListener("dotrix:runners", wrapped);
    },
  },
  app: {
    info: () => ipcRenderer.invoke("dotrix:app:info"),
    changelog: () => ipcRenderer.invoke("dotrix:app:changelog"),
  },
  updates: {
    state: () => ipcRenderer.invoke("dotrix:updates:state"),
    check: () => ipcRenderer.invoke("dotrix:updates:check"),
    install: () => ipcRenderer.invoke("dotrix:updates:install"),
    onChange: (listener: (state: unknown) => void) => {
      const wrapped = (_event: unknown, state: unknown) => listener(state);
      ipcRenderer.on("dotrix:updates", wrapped);
      return () => ipcRenderer.removeListener("dotrix:updates", wrapped);
    },
  },
  notify: {
    supported: () => ipcRenderer.invoke("dotrix:notify:supported"),
    show: (notice: { id: string; title: string; body: string; actions: string[] }) => ipcRenderer.invoke("dotrix:notify:show", notice),
    onAction: (listener: (id: string, action: string | null) => void) => {
      const wrapped = (_event: unknown, id: string, action: string | null) => listener(id, action);
      ipcRenderer.on("dotrix:notify", wrapped);
      return () => ipcRenderer.removeListener("dotrix:notify", wrapped);
    },
  },
  browser: {
    settings: () => ipcRenderer.invoke("dotrix:browser:settings"),
    setKeepCookies: (keep: boolean) => ipcRenderer.invoke("dotrix:browser:keep-cookies", keep),
    clear: () => ipcRenderer.invoke("dotrix:browser:clear"),
    setEnabled: (enabled: boolean) => ipcRenderer.invoke("dotrix:browser:enabled", enabled),
    setKaiAllowed: (allowed: boolean) => ipcRenderer.invoke("dotrix:browser:kai-allowed", allowed),
    kaiRequest: () => ipcRenderer.invoke("dotrix:browser:kai-request"),
    kaiReady: (id: number, contentsId: number) => ipcRenderer.invoke("dotrix:browser:kai-ready", id, contentsId),
    onKai: (listener: (request: { id: number; url: string }) => void) => {
      const wrapped = (_event: unknown, request: { id: number; url: string }) => listener(request);
      ipcRenderer.on("dotrix:browser:kai", wrapped);
      return () => ipcRenderer.removeListener("dotrix:browser:kai", wrapped);
    },
    onOpen: (listener: (url: string) => void) => {
      const wrapped = (_event: unknown, url: string) => listener(url);
      ipcRenderer.on("dotrix:browser:open", wrapped);
      return () => ipcRenderer.removeListener("dotrix:browser:open", wrapped);
    },
  },
  worktree: {
    tree: (worktree: string) => ipcRenderer.invoke("dotrix:worktree:tree", worktree),
    file: (worktree: string, file: string) => ipcRenderer.invoke("dotrix:worktree:file", worktree, file),
    open: (worktree: string) => ipcRenderer.invoke("dotrix:worktree:open", worktree),
    reveal: (worktree: string) => ipcRenderer.invoke("dotrix:worktree:reveal", worktree),
  },
});
