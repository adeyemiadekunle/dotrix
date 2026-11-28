import { Input as DesignInput } from "@dotrix/ui/components/input";
import { ActionButton } from "@dotrix/ui/components/action-button";
import { useEffect, useState } from "react";
import { Ic } from "../core/icons";
import { sharedSecretDeleted, sharedSecrets, sharedSecretSaved, type SharedSecret } from "../data/account";
import { isLive } from "../data/live";
import { toast } from "../ui/toast";

type Draft = { name: string; host: string; header: string; prefix: string; value: string };
const NEW: Draft = { name: "", host: "", header: "Authorization", prefix: "Bearer ", value: "" };

/** The workspace's shared secrets: kept once here, used by a project only when it references one by name (in its
 *  Edit environment → Secrets). Values are write-only. */
export function SharedSecrets() {
  const [items, setItems] = useState<SharedSecret[]>([]);
  const [error, setError] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isLive()) return;
    let on = true;
    sharedSecrets()
      .then((list) => on && setItems(list))
      .catch((e: unknown) => on && setError(e instanceof Error && e.message ? e.message : "It didn't load"));
    return () => {
      on = false;
    };
  }, []);

  const editing = Boolean(draft && items.some((s) => s.name === draft.name));
  const ready = Boolean(draft && /^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(draft.name.trim()) && draft.host.trim() && (editing || draft.value));

  const save = async () => {
    if (!draft || !ready) return;
    if (!isLive()) {
      toast("Saved");
      setDraft(null);
      return;
    }
    setBusy(true);
    try {
      const saved = await sharedSecretSaved(draft.name.trim(), {
        host: draft.host.trim(),
        header: draft.header.trim() || "Authorization",
        prefix: draft.prefix,
        value: draft.value ? draft.value : null,
      });
      setItems([...items.filter((s) => s.name !== saved.name), saved].sort((a, b) => a.name.localeCompare(b.name)));
      toast("Shared secret saved");
      setDraft(null);
    } catch (e) {
      toast(`It didn't save: ${e instanceof Error && e.message ? e.message : "try again"}`, { kind: "err", ms: 7000 });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: SharedSecret) => {
    const used = item.projects ? ` ${item.projects} ${item.projects === 1 ? "project uses" : "projects use"} it and will go on without it.` : "";
    if (!window.confirm(`Delete the shared secret ${item.name}?${used}`)) return;
    try {
      if (isLive()) await sharedSecretDeleted(item.name);
      setItems(items.filter((s) => s.name !== item.name));
      toast("Shared secret deleted");
    } catch (e) {
      toast(`It didn't delete: ${e instanceof Error && e.message ? e.message : "try again"}`, { kind: "err", ms: 7000 });
    }
  };

  return (
    <div className="sblock">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <h2 style={{ margin: 0 }}>Shared secrets</h2>
        {!draft && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDraft(NEW)}>
            Add shared secret
          </button>
        )}
      </div>
      <p className="faint" style={{ marginTop: 6 }}>
        A token kept once for the workspace, such as a private registry's. A project uses it only when its environment references it by name, and its host must
        be in that project's network access. Kai only ever sees a placeholder.
      </p>
      {error && <div className="alert danger">{error}</div>}
      {items.length > 0 && (
        <ul className="env-secrets" aria-label="Shared secrets" style={{ maxWidth: 520 }}>
          {items.map((s) => (
            <li key={s.name}>
              <button
                type="button"
                className="env-secret"
                onClick={() => setDraft({ name: s.name, host: s.host, header: s.header, prefix: s.prefix, value: "" })}
              >
                <span className="mono">{s.name}</span>
                <span className="faint">
                  {s.host} · {s.projects === 0 ? "no projects use it" : `${s.projects} ${s.projects === 1 ? "project" : "projects"}`}
                </span>
              </button>
              <button type="button" className="ibtn" aria-label={`Delete ${s.name}`} onClick={() => remove(s)}>
                <Ic n="trash-2" s={15} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {draft && (
        <div className="env-shared-form" role="group" aria-label={editing ? "Edit shared secret" : "Add shared secret"}>
          <label>
            <span>Variable name</span>
            <DesignInput
              className="mono"
              value={draft.name}
              disabled={editing}
              onChange={(e) => setDraft({ ...draft, name: e.target.value.toUpperCase() })}
              placeholder="NPM_TOKEN"
            />
          </label>
          <label>
            <span>Host</span>
            <DesignInput className="mono" value={draft.host} onChange={(e) => setDraft({ ...draft, host: e.target.value })} placeholder="registry.npmjs.org" />
          </label>
          <label>
            <span>Header</span>
            <DesignInput className="mono" value={draft.header} onChange={(e) => setDraft({ ...draft, header: e.target.value })} placeholder="Authorization" />
          </label>
          <label>
            <span>Before the value</span>
            <DesignInput className="mono" value={draft.prefix} onChange={(e) => setDraft({ ...draft, prefix: e.target.value })} placeholder="Bearer " />
          </label>
          <label>
            <span>Value</span>
            <DesignInput
              type="password"
              autoComplete="off"
              className="mono"
              value={draft.value}
              onChange={(e) => setDraft({ ...draft, value: e.target.value })}
              placeholder={editing ? "Leave empty to keep the saved value" : ""}
            />
          </label>
          <div className="row" style={{ gap: 8 }}>
            <ActionButton className="btn btn-primary btn-sm" disabled={!ready || busy} onClick={save}>
              Save shared secret
            </ActionButton>
            <ActionButton className="btn btn-secondary btn-sm" disabled={busy} onClick={() => setDraft(null)}>
              Cancel
            </ActionButton>
          </div>
        </div>
      )}
    </div>
  );
}
