import { Ic } from "../core/icons";

/** Why a turn's changes wait in every approval mode: they change files CI runs. */
export function CiSensitiveNote({ files }: { files: string[] }) {
  return (
    <div className="alert warn" role="note" style={{ margin: "0 12px 8px" }}>
      <Ic n="triangle-alert" s={15} />
      <div>
        They change files CI runs ({files.slice(0, 5).join(", ")}
        {files.length > 5 ? ` and ${files.length - 5} more` : ""}), which its checks would run with the repository's secrets. Check them before accepting.
      </div>
    </div>
  );
}
