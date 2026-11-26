import type { Schemas } from "@dotrix/api-client";
import { useId } from "react";

import { PRIVACY_URL, TERMS_URL } from "../src/core/constants";

// Keep this in sync with TermsVersion.CURRENT and the published Terms of Service.
export const TERMS_VERSION = "2026-11-26" satisfies Schemas["TermsVersion"];

export function TermsAcceptance({ onChange }: { onChange?: (accepted: boolean) => void }) {
  const id = useId();
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <input
        id={id}
        name="accept_terms"
        type="checkbox"
        required
        className="mt-0.5 size-4 shrink-0 accent-current"
        onChange={(event) => onChange?.(event.target.checked)}
      />
      <label htmlFor={id}>
        I accept the{" "}
        <a href={TERMS_URL} target="_blank" rel="noreferrer" className="underline underline-offset-4">
          Terms of Service
        </a>{" "}
        and acknowledge the{" "}
        <a href={PRIVACY_URL} target="_blank" rel="noreferrer" className="underline underline-offset-4">
          Privacy Policy
        </a>
        .
      </label>
    </div>
  );
}
