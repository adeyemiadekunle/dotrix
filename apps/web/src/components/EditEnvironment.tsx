import { Textarea as DesignTextarea } from "@dotrix/ui/components/textarea";
import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { SelectField } from "@dotrix/ui/components/select";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Ic } from "../core/icons";
import { formatDotenv, parseDotenv } from "../core/dotenv";
import { cloudEnvironment, cloudEnvironmentSaved, type CloudEnvironment, type SandboxNetwork } from "../data/account";
import { isLive } from "../data/live";
import { toast } from "../ui/toast";

type Preset = { label: string; hosts: string[] };

/** What a project's network policy lets its sessions reach besides the model API, in a few words. */
export function networkSummary(presets: string[], hosts: string[], available: Record<string, Preset>): string {
  const names = presets.map((p) => available[p]?.label.split(" (")[0] ?? p);
  const parts = [...names, ...(hosts.length ? [`${hosts.length} ${hosts.length === 1 ? "host" : "hosts"}`] : [])];
  return parts.length ? parts.join(", ") : "Model API only";
}

const SAMPLE: CloudEnvironment = {
  revision: 0,
  enabled: true,
  name: "Project environment",
  image: null,
  setup_script: "#!/bin/bash\nnpm ci",
  verify_script: "npm test",
  timeout_seconds: 300,
  variables: { LOG_LEVEL: "debug" },
  image_policy: "platform",
  available_images: [],
};

/** A project's environment as one form: name, network access, setup script and variables (and, under More settings,
 *  the verification command, image and time limit). Network access is the project's network policy, saved with the
 *  environment. New cloud sessions keep the version they start with. A sheet on phones, a dialog elsewhere. */
export function EditEnvironment({
  projectId,
  network,
  onClose,
  onSaved,
}: {
  projectId: string;
  network: SandboxNetwork;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [loaded, setLoaded] = useState<CloudEnvironment | null>(isLive() ? null : SAMPLE);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState<CloudEnvironment | null>(isLive() ? null : SAMPLE);
  const [variables, setVariables] = useState(isLive() ? "" : formatDotenv(SAMPLE.variables ?? {}));
  const [presets, setPresets] = useState<string[]>(network.presets);
  const [hosts, setHosts] = useState(network.hosts.join("\n"));
  const [view, setView] = useState<"main" | "network">("main");
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const available = network.available_presets as Record<string, Preset>;

  useEffect(() => {
    if (!isLive()) return;
    let on = true;
    cloudEnvironment(projectId)
      .then((env) => {
        if (!on) return;
        setLoaded(env);
        setForm(env);
        setVariables(formatDotenv(env.variables ?? {}));
        setMore(Boolean(env.verify_script || env.image));
      })
      .catch((e: unknown) => on && setLoadError(e instanceof Error && e.message ? e.message : "It didn't load"));
    return () => {
      on = false;
    };
  }, [projectId]);
  useEffect(() => dialog.current?.querySelector<HTMLElement>("input,textarea,button")?.focus(), [view, form === null]);

  const parsed = parseDotenv(variables);
  const typedHosts = hosts.split(/[\s,]+/).filter(Boolean);
  const change = (patch: Partial<CloudEnvironment>) => form && setForm({ ...form, ...patch });

  const chooseFile = async (f: File | undefined) => {
    if (!f || !form) return;
    if (f.size > 16000) {
      toast("That file is over 16,000 characters", { kind: "err" });
      return;
    }
    change({ setup_script: await f.text() });
  };

  const save = async () => {
    if (!form || parsed.error) return;
    const vars = parsed.variables;
    const body = {
      revision: form.revision,
      // An environment applies once it has something to apply; an empty one leaves sessions as they are.
      enabled: Boolean(form.setup_script.trim() || form.verify_script.trim() || form.image || Object.keys(vars).length),
      name: form.name.trim() || "Project environment",
      image: form.image ?? null,
      setup_script: form.setup_script,
      verify_script: form.verify_script,
      timeout_seconds: form.timeout_seconds,
      variables: vars,
      network: { presets, hosts: typedHosts },
    };
    if (!isLive()) {
      toast("Saved");
      onClose();
      return;
    }
    setBusy(true);
    try {
      await cloudEnvironmentSaved(projectId, body);
      toast("Environment saved");
      onSaved();
      onClose();
    } catch (e) {
      toast(`It didn't save: ${e instanceof Error && e.message ? e.message : "try again"}`, { kind: "err", ms: 7000 });
    } finally {
      setBusy(false);
    }
  };

  const close = () => (view === "network" ? setView("main") : onClose());
  const title = view === "network" ? "Network access" : "Edit environment";
  return (
    <div>
      {/* Above the agents launcher (73), below popovers (80) and toasts (100). */}
      <div className="scrim enter" onClick={onClose} style={{ zIndex: 74 }} />
      <div
        className="modal-wrap"
        style={{ zIndex: 75 }}
        onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        onKeyDown={(e) => e.key === "Escape" && (e.stopPropagation(), close())}
      >
        <div ref={dialog} className="modal enter env-sheet" role="dialog" aria-modal="true" aria-labelledby="env-sheet-title">
          <div className="env-sheet-h">
            <button className="ibtn" onClick={close} aria-label={view === "network" ? "Back" : "Close"}>
              <Ic n={view === "network" ? "chevron-left" : "x"} s={18} />
            </button>
            <h2 id="env-sheet-title">{title}</h2>
            <span aria-hidden style={{ width: 32 }} />
          </div>
          <div className="modal-b">
            {loadError ? (
              <div className="alert danger">{loadError}</div>
            ) : !form || !loaded ? (
              <div className="faint">Loading…</div>
            ) : view === "network" ? (
              <>
                <p className="faint" style={{ margin: 0 }}>
                  Kai's sandboxes reach only the model API and what you allow here. Each host is somewhere an agent could also send your code.
                  {network.limited && (
                    <>
                      {" "}
                      Within the workspace's limit: <span className="mono">{(network.limit ?? []).join(", ") || "no hosts"}</span>.
                    </>
                  )}
                </p>
                <EnvField label="Package registries">
                  {Object.entries(available).map(([key, preset]) => (
                    <label key={key} className="env-check">
                      <input
                        type="checkbox"
                        checked={presets.includes(key)}
                        onChange={(e) => setPresets(e.target.checked ? [...presets, key] : presets.filter((p) => p !== key))}
                      />
                      <span>
                        {preset.label}
                        <span className="mono faint" style={{ display: "block", fontSize: 12 }}>
                          {preset.hosts.join(", ")}
                        </span>
                      </span>
                    </label>
                  ))}
                </EnvField>
                <EnvField
                  label="Other hosts"
                  id="env-hosts"
                  help={
                    <>
                      One per line: <span className="mono">api.example.com</span>, <span className="mono">*.example.com</span> or{" "}
                      <span className="mono">registry.example.com:8443</span> (443 if none). HTTPS only.
                    </>
                  }
                >
                  <DesignTextarea
                    id="env-hosts"
                    className="textarea mono"
                    rows={4}
                    value={hosts}
                    onChange={(e) => setHosts(e.target.value)}
                    placeholder="api.example.com"
                  />
                </EnvField>
              </>
            ) : (
              <>
                <EnvField label="Name" id="env-name">
                  <DesignInput id="env-name" value={form.name} maxLength={100} onChange={(e) => change({ name: e.target.value })} />
                </EnvField>
                <EnvField label="Network access">
                  <button type="button" className="env-pick" onClick={() => setView("network")} aria-label="Network access">
                    <span>{networkSummary(presets, typedHosts, available)}</span>
                    <Ic n="chevron-right" s={16} />
                  </button>
                </EnvField>
                <EnvField
                  label="Setup script"
                  id="env-setup"
                  action={
                    <>
                      <button type="button" className="btn btn-secondary btn-sm" onClick={() => file.current?.click()}>
                        Choose file
                      </button>
                      <input
                        ref={file}
                        type="file"
                        accept=".sh,.bash,text/x-shellscript,text/plain"
                        hidden
                        onChange={(e) => (void chooseFile(e.target.files?.[0]), (e.target.value = ""))}
                      />
                    </>
                  }
                  help="Runs in a fresh cloud sandbox before Kai starts. Use frozen installs; a script that changes repository files fails the turn."
                >
                  <DesignTextarea
                    id="env-setup"
                    className="textarea mono"
                    rows={5}
                    value={form.setup_script}
                    onChange={(e) => change({ setup_script: e.target.value })}
                    maxLength={16000}
                    placeholder={"#!/bin/bash\nnpm ci"}
                  />
                </EnvField>
                <EnvField
                  label="Environment variables"
                  id="env-vars"
                  help={
                    parsed.error ? (
                      <span className="env-err">{parsed.error}</span>
                    ) : (
                      "One KEY=value per line, in .env format. Anyone who uses this environment can see these values, and so can Kai, so don't put secrets here."
                    )
                  }
                >
                  <DesignTextarea
                    id="env-vars"
                    className="textarea mono"
                    rows={4}
                    value={variables}
                    onChange={(e) => setVariables(e.target.value)}
                    placeholder="LOG_LEVEL=debug"
                    aria-invalid={Boolean(parsed.error)}
                  />
                </EnvField>
                <button type="button" className="env-more" onClick={() => setMore(!more)} aria-expanded={more}>
                  <Ic n={more ? "chevron-down" : "chevron-right"} s={14} />
                  More settings
                </button>
                {more && (
                  <>
                    <EnvField
                      label="Verification command"
                      id="env-verify"
                      help="Must pass before changes can be accepted. Runs with the repository read-only; write test artifacts to $TMPDIR."
                    >
                      <DesignTextarea
                        id="env-verify"
                        className="textarea mono"
                        rows={3}
                        value={form.verify_script}
                        onChange={(e) => change({ verify_script: e.target.value })}
                        maxLength={16000}
                        placeholder="npm test"
                      />
                    </EnvField>
                    <EnvField label="Coding image" help="Custom images must be approved by the server operator and pinned by digest. Docker only.">
                      <SelectField
                        title={form.image ?? "Platform coding image"}
                        aria-label="Coding image"
                        value={form.image ?? ""}
                        onValueChange={(value) => change({ image: value || null })}
                        options={[
                          { value: "", label: "Platform coding image" },
                          ...(form.image && !(form.available_images ?? []).includes(form.image)
                            ? [{ value: form.image, label: `No longer approved: ${form.image}` }]
                            : []),
                          ...(form.available_images ?? []).map((image) => ({ value: image, label: image })),
                        ]}
                      />
                    </EnvField>
                    <EnvField label="Time limit per script" id="env-timeout" help="10–900 seconds">
                      <DesignInput
                        id="env-timeout"
                        type="number"
                        min={10}
                        max={900}
                        value={form.timeout_seconds}
                        onChange={(e) => change({ timeout_seconds: Number(e.target.value) })}
                      />
                    </EnvField>
                  </>
                )}
                <p className="faint" style={{ margin: 0, fontSize: 12.5 }}>
                  New cloud sessions use this version; sessions already running keep theirs. Coding on a person's computer uses that computer's own setup, and
                  only the network access applies there.
                </p>
              </>
            )}
          </div>
          <div className="modal-f">
            {view === "network" ? (
              <ActionButton className="btn btn-primary env-save" onClick={() => setView("main")}>
                Done
              </ActionButton>
            ) : (
              <ActionButton className="btn btn-primary env-save" disabled={!form || busy || Boolean(parsed.error)} onClick={save}>
                Save changes
              </ActionButton>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function EnvField({ label, id, action, help, children }: { label: string; id?: string; action?: ReactNode; help?: ReactNode; children: ReactNode }) {
  return (
    <div className="env-field">
      <div className="env-field-h">
        {id ? <label htmlFor={id}>{label}</label> : <span>{label}</span>}
        {action}
      </div>
      {children}
      {help && <div className="env-help">{help}</div>}
    </div>
  );
}
