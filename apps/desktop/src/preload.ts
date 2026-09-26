// Bridge between the web UI and native features. Expose only narrow, explicit APIs.
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("pmagentDesktop", {
  platform: process.platform,
});
