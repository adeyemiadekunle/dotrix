// A run that stopped at its model's limit (the person's key, or the workspace's): what happened,
// when it resets if the provider said, and Continue now or when it resets. In Chat under the
// reply where it stopped, and in Notifications.
import { Ic } from "../core/icons";

function resetsIn(at: number | null): string {
  if (at == null) return "";
  const min = Math.ceil((at - Date.now()) / 60_000);
  return min <= 0 ? " The limit should have reset by now." : ` It resets in about ${min} minute${min === 1 ? "" : "s"}.`;
}

export function LimitNotice({
  provider,
  said,
  resetsAt,
  whenReset,
  onContinue,
}: {
  provider?: string;
  said?: string;
  resetsAt: number | null;
  whenReset?: boolean;
  onContinue: (whenReset: boolean) => void;
}) {
  const later = resetsAt != null && resetsAt > Date.now();
  return (
    <div className="alert warn" role="status" style={{ marginTop: 8 }}>
      <Ic n="gauge" s={16} />
      <div style={{ flex: 1 }}>
        <b>Stopped at {provider ? `${provider}'s` : "the model's"} limit.</b> {said ? `${said}.` : "The key reached its rate limit, quota, or credit."}
        {resetsIn(resetsAt)} Nothing is lost: it continues from where it stopped.
        <div className="row" style={{ gap: 6, marginTop: 8 }}>
          {whenReset ? (
            <span className="faint" style={{ fontSize: 12.5 }}>
              It&apos;ll continue by itself when the limit resets.
            </span>
          ) : (
            <>
              <button className="btn btn-sm btn-primary" onClick={() => onContinue(false)}>
                Continue now
              </button>
              {(later || resetsAt == null) && (
                <button className="btn btn-sm btn-secondary" onClick={() => onContinue(true)}>
                  Continue when it resets
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
