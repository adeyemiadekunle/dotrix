import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, authPost, unwrap } from "@/lib/api";
import { go, useRoute } from "../core/nav";
import { myKeySaved, myModels, modelKeySaved } from "../data/account";
import { isLive, live } from "../data/live";
import { D } from "../data/store";

/** A real workspace needs at least one authorized provider before the app can be used. */
export function ModelGate({ children }: { children: ReactNode }) {
  const { route, params } = useRoute();
  const workspace = isLive() ? live.ws?.id : undefined;
  const qc = useQueryClient();
  const access = useQuery({
    queryKey: ["model-access", workspace],
    enabled: !!workspace,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/model-keys/access", { params: { path: { workspace_id: workspace! } } })),
    refetchOnWindowFocus: true,
  });
  const providers = useQuery({ queryKey: ["my-models"], queryFn: myModels, enabled: !!workspace && access.data?.ready === false });
  const [provider, setProvider] = useState("openai");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [shared, setShared] = useState(false);
  // Key settings remain reachable so members can fix policy/configuration without being trapped.
  const keySettings = route === "settings" && (params.sec === "my-models" || params.sec === "models");
  if (!workspace || access.data?.ready || keySettings) return children;
  const d = access.data;
  const workspaceKey = d?.personal_keys_allowed === false || shared;
  const allowed = d?.can_store_keys && (workspaceKey ? d.can_manage_keys : d.personal_keys_allowed);
  const connect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!allowed || busy) return;
    setBusy(true);
    setError("");
    try {
      if (workspaceKey) await modelKeySaved(provider, key.trim());
      else await myKeySaved(provider, key.trim());
      setKey("");
      await qc.invalidateQueries();
      await access.refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The key could not be saved");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="fullstate" style={{ minHeight: "100svh" }}>
      <div className="box" style={{ width: "min(100% - 32px, 480px)", textAlign: "left" }}>
        <h1>{d ? "Connect a model to continue" : "Checking your models…"}</h1>
        <p className="muted">
          {d
            ? "This workspace has no available model provider. Connect a key to use chat and coding. Your key is stored encrypted."
            : "Checking your personal, workspace, and platform providers."}
        </p>
        {access.error && (
          <div role="alert" className="alert danger">
            {access.error.message}
            <button className="btn btn-secondary" onClick={() => void access.refetch()}>
              Try again
            </button>
          </div>
        )}
        {d && !d.can_store_keys && <p role="alert">Ask the platform administrator to enable encrypted key storage or connect a platform provider.</p>}
        {d && !d.personal_keys_allowed && !d.can_manage_keys && (
          <p role="alert">Your organisation uses its own keys. Ask an owner or administrator to connect a provider, or switch to your personal workspace.</p>
        )}
        {d?.can_manage_keys && d.personal_keys_allowed && (
          <label className="muted" style={{ display: "block", marginBottom: 16 }}>
            <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Connect a workspace key for everyone
          </label>
        )}
        {allowed && (
          <form onSubmit={(e) => void connect(e)} style={{ display: "grid", gap: 12 }}>
            <label>
              Provider
              <select className="select" value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Model provider">
                {(providers.data?.keys ?? []).map((p) => (
                  <option key={p.provider} value={p.provider}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              API key
              <input
                className="input"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={key}
                minLength={20}
                maxLength={400}
                required
                onChange={(e) => setKey(e.target.value)}
                aria-label="Model API key"
              />
            </label>
            {error && (
              <div className="alert danger" role="alert">
                {error}
              </div>
            )}
            <button className="btn btn-primary" type="submit" disabled={busy || !providers.data || key.trim().length < 20}>
              {busy ? "Connecting…" : "Connect and continue"}
            </button>
          </form>
        )}
        <div className="row" style={{ marginTop: 20 }}>
          {d && (
            <button
              className="btn btn-secondary"
              onClick={() => go("settings", { sec: d.can_manage_keys && !d.personal_keys_allowed ? "models" : "my-models" })}
            >
              Model settings
            </button>
          )}
          <a className="btn btn-secondary" href="/">
            Switch workspace
          </a>
          {D()
            .workspaces.filter((w) => w.slug && w.id !== workspace)
            .map((w) => (
              <a key={w.id} className="btn btn-secondary" href={`/w/${w.slug}`}>
                {w.name}
              </a>
            ))}
          <button className="btn btn-ghost" onClick={() => void authPost("logout").then(() => location.assign("/login"))}>
            Sign out
          </button>
        </div>
      </div>
    </main>
  );
}
