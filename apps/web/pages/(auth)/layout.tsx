import { ActionButton } from "@dotrix/ui/components/action-button";
import { AppShell, TopNav } from "@dotrix/ui/astryx";
import { useEffect, useState, type ReactNode } from "react";

import { setPref } from "@/src/core/actions";
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
    <AppShell
      className="auth"
      height="auto"
      variant="wash"
      contentPadding={0}
      topNav={
        <TopNav
          label="Account actions"
          heading={
            <a className="brand" href="/" aria-label="Home">
              <Logo h={22} />
            </a>
          }
          endContent={
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
          }
        />
      }
    >
      <div className="auth-c">{children}</div>
      <div className="auth-foot" style={{ padding: 18, fontSize: 12 }}>
        <span className="faint">© 2026 dotrix · Terms · Privacy</span>
      </div>
    </AppShell>
  );
}
