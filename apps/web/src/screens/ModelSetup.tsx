import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, authPost, unwrap } from "@/lib/api";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { Input as DesignInput } from "@dotrix/ui/components/input";
import { SelectField } from "@dotrix/ui/components/select";
import { Ic } from "../core/icons";
import { go, useRoute } from "../core/nav";
import { AGENTS, CODING_AGENT } from "../core/team";
import { myKeySaved, myModels } from "../data/account";
import { isLive, live } from "../data/live";
import { D } from "../data/store";
import { Face } from "../ui/face";

const NUDGE_DISMISSED_KEY = "dotrix.modelNudge.dismissed";

const KEY_PLACEHOLDERS: Record<string, string> = {
  openai: "sk-proj-...",
  anthropic: "sk-ant-...",
  google_genai: "AIza...",
  xai: "xai-...",
  nvidia: "nvapi-...",
  openrouter: "sk-or-...",
  deepseek: "sk-...",
  groq: "gsk_...",
  mistral: "...",
};

/** Model setup gates agent sessions while keeping project management and Settings available. */
export function ModelGate({ children }: { children: ReactNode }) {
  const { route } = useRoute();
  const workspace = isLive() ? live.ws?.id : undefined;
  const qc = useQueryClient();
  const access = useQuery({
    queryKey: ["model-access", workspace],
    enabled: !!workspace,
    queryFn: () => unwrap(api.GET("/v1/workspaces/{workspace_id}/model-access", { params: { path: { workspace_id: workspace! } } })),
    refetchOnWindowFocus: true,
  });
  const providers = useQuery({ queryKey: ["my-models"], queryFn: myModels, enabled: !!workspace && access.data?.ready === false });
  const [provider, setProvider] = useState("openai");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nudgeHidden, setNudgeHidden] = useState(() => {
    try {
      return sessionStorage.getItem(NUDGE_DISMISSED_KEY) === "1";
    } catch {
      return false;
    }
  });

  if (!workspace || access.data?.ready || route === "settings") return children;
  if (route !== "chat" && route !== "codes") {
    const dismissNudge = () => {
      setNudgeHidden(true);
      try {
        sessionStorage.setItem(NUDGE_DISMISSED_KEY, "1");
      } catch {
        /* ignore */
      }
    };
    return (
      <>
        {access.data?.ready === false && !nudgeHidden && (
          <div className="model-nudge" role="status">
            <span className="model-nudge-icon" aria-hidden="true">
              <Ic n="key-round" s={14} />
            </span>
            <span className="model-nudge-copy">
              <b>Model key optional right now.</b> Connect your API key whenever you&apos;re ready to use Chat and Code — tasks and docs work without one.
            </span>
            <div className="model-nudge-acts">
              <ActionButton className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "my-models" })}>
                Connect a model
              </ActionButton>
              <button type="button" className="ibtn ibtn-xs" onClick={dismissNudge} aria-label="Dismiss model setup notice">
                <Ic n="x" s={13} />
              </button>
            </div>
          </div>
        )}
        {children}
      </>
    );
  }

  const d = access.data;
  const allowed = d?.can_store_keys;
  const novaColor = AGENTS[0]?.c ?? "#E0A92E";
  const otherWorkspaces = D().workspaces.filter((w) => w.slug && w.id !== workspace);
  const selectedLabel = providers.data?.keys.find((p) => p.provider === provider)?.label ?? "Provider";

  const connect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!allowed || busy) return;
    setBusy(true);
    setError("");
    try {
      await myKeySaved(provider, key.trim());
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
    <section aria-label="Model setup" className="model-gate">
      <div className="model-gate-card">
        <div className="model-gate-top">
          <div className="model-gate-faces" aria-hidden="true">
            <Face c={novaColor} size={32} />
            <Face c={CODING_AGENT.c} size={32} />
          </div>
          <span className="badge gray">
            <Ic n="lock" s={11} />
            Encrypted BYOK
          </span>
        </div>

        <div className="model-gate-head">
          <h1>{d ? "Connect a model to continue" : "Checking your models…"}</h1>
          <p>
            {d
              ? "Bring your own API key to unlock Nova in Chat and Kai in Code. Your key is stored encrypted and billed only to your provider account."
              : "Checking your connected model providers."}
          </p>
        </div>

        {access.error && (
          <div role="alert" className="alert danger">
            <Ic n="triangle-alert" s={15} />
            <div className="grow">{access.error.message}</div>
            <button className="btn btn-secondary btn-sm" onClick={() => void access.refetch()}>
              Try again
            </button>
          </div>
        )}

        {d && !d.can_store_keys && (
          <div role="alert" className="alert warn">
            <Ic n="shield-alert" s={15} />
            <span>Ask the platform administrator to enable encrypted key storage before adding an API key.</span>
          </div>
        )}

        {allowed && (
          <form className="model-gate-form" onSubmit={(e) => void connect(e)}>
            <div className="field">
              <span className="label">Provider</span>
              <SelectField
                aria-label="Model provider"
                className="w-full"
                value={provider}
                onValueChange={setProvider}
                options={(providers.data?.keys ?? []).map((p) => ({ value: p.provider, label: p.label }))}
              />
            </div>

            <div className="field">
              <label className="label" htmlFor="model-gate-api-key">
                API key
              </label>
              <DesignInput
                id="model-gate-api-key"
                className="input mono"
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder={KEY_PLACEHOLDERS[provider] ?? `Paste your ${selectedLabel} API key`}
                value={key}
                minLength={20}
                maxLength={400}
                required
                onChange={(e) => setKey(e.target.value)}
                aria-label="Model API key"
              />
              <span className="model-gate-hint">Private to your account · Never exposed to teammates or client logs</span>
            </div>

            {error && (
              <div className="alert danger" role="alert">
                <Ic n="circle-alert" s={15} />
                <span>{error}</span>
              </div>
            )}

            <button className="btn btn-primary model-gate-submit" type="submit" disabled={busy || !providers.data || key.trim().length < 20}>
              {busy ? "Connecting…" : "Connect and continue"}
              {!busy && <Ic n="arrow-right" s={14} />}
            </button>
          </form>
        )}

        <div className="model-gate-perks">
          <span>
            <Ic n="shield-check" s={13} />
            Encrypted at rest
          </span>
          <span>
            <Ic n="sliders-horizontal" s={13} />
            Switch models anytime
          </span>
          <span>
            <Ic n="folder-kanban" s={13} />
            Projects stay unlocked
          </span>
        </div>

        <div className="model-gate-foot">
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            {d && (
              <button className="btn btn-secondary btn-sm" onClick={() => go("settings", { sec: "my-models" })}>
                <Ic n="settings-2" s={13} />
                Model settings
              </button>
            )}
            {otherWorkspaces.map((w) => (
              <a key={w.id} className="btn btn-secondary btn-sm" href={`/w/${w.slug}`}>
                {w.name}
              </a>
            ))}
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => void authPost("logout").then(() => location.assign("/login"))}>
            Sign out
          </button>
        </div>
      </div>
    </section>
  );
}
