import { ActionButton } from "@dotrix/ui/components/action-button";
import { useEffect, useState, type ReactNode } from "react";

import { setPref } from "@/src/core/actions";
import { PRIVACY_URL, TERMS_URL } from "@/src/core/constants";
import { Ic, Logo } from "@/src/core/icons";
import { applyPrefs, effectiveDark } from "@/src/core/theme";

/** Auth shell: the wordmark and a theme toggle
 * on top, the card in the middle, small print below. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  const [, flip] = useState(0);
  useEffect(() => {
    applyPrefs();
  }, []);
  return (
    <div className="auth">
      <div className="auth-top">
        <a className="brand" href="/" aria-label="Home">
          <Logo h={22} />
        </a>
        <div className="row">
          <ActionButton
            className="ibtn"
            onClick={() => {
              setPref("theme", effectiveDark() ? "light" : "dark");
              applyPrefs(); // these pages have no workspace shell to apply it on its next render
              flip((n) => n + 1);
            }}
            data-tip="Toggle theme"
            aria-label="Toggle theme"
          >
            <Ic n={effectiveDark() ? "sun" : "moon"} s={16} />
          </ActionButton>
        </div>
      </div>
      <main className="auth-c">{children}</main>
      <div className="auth-foot" style={{ padding: 18, fontSize: 12 }}>
        <span className="faint">
          © 2026 dotrix ·{" "}
          <a href={TERMS_URL} target="_blank" rel="noreferrer">
            Terms
          </a>{" "}
          ·{" "}
          <a href={PRIVACY_URL} target="_blank" rel="noreferrer">
            Privacy
          </a>
        </span>
      </div>
    </div>
  );
}
