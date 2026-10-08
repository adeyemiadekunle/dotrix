import { useEffect, useState, type ReactNode } from "react";

import { setPref } from "@/src/core/actions";
import { Ic, Logo } from "@/src/core/icons";
import { applyPrefs, effectiveDark } from "@/src/core/theme";

/** Gr8r's auth shell (gr8r-studio/src/pages/auth.js authShell): the wordmark and a theme toggle
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
          <button
            className="ibtn"
            onClick={() => {
              setPref("theme", effectiveDark() ? "light" : "dark");
              flip((n) => n + 1);
            }}
            data-tip="Toggle theme"
            aria-label="Toggle theme"
          >
            <Ic n={effectiveDark() ? "sun" : "moon"} s={16} />
          </button>
        </div>
      </div>
      <div className="auth-c">{children}</div>
      <div className="auth-foot" style={{ padding: 18, fontSize: 12 }}>
        <span className="faint">© 2026 dotrix · Terms · Privacy</span>
      </div>
    </div>
  );
}
