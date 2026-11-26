import { useEffect, useRef, useState } from "react";

import { WEB_ANALYTICS_TOKEN } from "./config";

const COOKIE = "dotrix_cookie_consent";
const MAX_AGE = 180 * 24 * 60 * 60;
const BEACON_ID = "dotrix-web-analytics";
type Choice = "accepted" | "rejected";

function savedChoice(): Choice | null {
  const value = document.cookie
    .split("; ")
    .find((cookie) => cookie.startsWith(`${COOKIE}=`))
    ?.slice(COOKIE.length + 1);
  return value === "accepted" || value === "rejected" ? value : null;
}

export function useCookieConsent() {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<Choice | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const fromSettings = useRef(false);

  useEffect(() => {
    const saved = savedChoice();
    setChoice(saved);
    setOpen(saved === null);
  }, []);

  useEffect(() => {
    if (open && fromSettings.current) heading.current?.focus();
  }, [open]);

  useEffect(() => {
    if (choice !== "accepted" || !WEB_ANALYTICS_TOKEN || document.getElementById(BEACON_ID)) return;
    const script = document.createElement("script");
    script.id = BEACON_ID;
    script.type = "module";
    script.src = "https://static.cloudflareinsights.com/beacon.min.js";
    script.setAttribute("data-cf-beacon", JSON.stringify({ token: WEB_ANALYTICS_TOKEN }));
    document.head.append(script);
  }, [choice]);

  function choose(next: Choice) {
    const secure = location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${COOKIE}=${next}; Max-Age=${MAX_AGE}; Path=/; SameSite=Lax${secure}`;
    setChoice(next);
    setOpen(false);
    if (fromSettings.current) trigger.current?.focus();
    fromSettings.current = false;
    // A loaded beacon has page listeners. Reload without it after withdrawing consent.
    if (next === "rejected" && document.getElementById(BEACON_ID)) {
      // Block the beacon's final page-exit request before discarding its listeners.
      const policy = document.createElement("meta");
      policy.httpEquiv = "Content-Security-Policy";
      policy.content = "connect-src 'none'";
      document.head.append(policy);
      document.getElementById(BEACON_ID)?.remove();
      location.reload();
    }
  }

  function openSettings() {
    fromSettings.current = true;
    if (open) heading.current?.focus();
    else setOpen(true);
  }

  return {
    settings: (
      <button
        ref={trigger}
        type="button"
        className="cookie-settings"
        onClick={openSettings}
        aria-expanded={open}
        aria-controls={open ? "cookie-consent" : undefined}
      >
        Cookie settings
      </button>
    ),
    banner: open && (
      <section id="cookie-consent" className="cookie-consent" aria-labelledby="cookie-consent-title">
        <div>
          <h2 id="cookie-consent-title" ref={heading} tabIndex={-1}>
            Cookie preferences
          </h2>
          <p>
            Essential cookies keep sign-in working and remember this choice. If you accept, Cloudflare Web Analytics measures visits and page views.{" "}
            <a href="/privacy#cookies">Privacy policy</a>
          </p>
        </div>
        <div className="cookie-actions">
          <button type="button" className="btn btn-soft btn-sm" onClick={() => choose("rejected")}>
            Reject analytics
          </button>
          <button type="button" className="btn btn-soft btn-sm" onClick={() => choose("accepted")}>
            Accept analytics
          </button>
        </div>
      </section>
    ),
  };
}
