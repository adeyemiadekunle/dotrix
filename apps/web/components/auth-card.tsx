import type { ReactNode } from "react";

import { Logo } from "@/src/core/icons";

/** Gr8r's auth card: the wordmark, a heading, a line under it, the form, and a footer line. */
export function AuthCard({ title, description, children, footer }: { title: string; description?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth-card">
      <div style={{ display: "flex", justifyContent: "center" }}>
        <Logo h={30} />
      </div>
      <h1>{title}</h1>
      {description && <p className="sub">{description}</p>}
      {children}
      {footer && <p className="auth-foot">{footer}</p>}
    </div>
  );
}
