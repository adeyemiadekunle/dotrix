# Astryx and Tailwind in Dotrix

Dotrix uses Astryx 0.7.15's prebuilt components and a precompiled custom theme. React 19, the StyleX runtime, theme CSS, `Theme`, internationalization, and layer providers are already installed. A StyleX/Babel compilation plugin or a second neutral theme is not required for this consumption path.

References: [Getting started](https://astryx.atmeta.com/docs/getting-started), [official core setup guide](https://github.com/meta/astryx/blob/main/packages/core/README.md). The installed version's guide is available without the website:

```sh
pnpm --filter @dotrix/ui astryx docs styling-libraries/tailwind --full
pnpm --filter @dotrix/ui astryx component Button
```

## CSS ownership

`packages/ui/src/styles/globals.css` declares the full layer order **before** importing Tailwind:

```css
@layer reset, theme, base, astryx-base, astryx-theme, components, utilities;
```

Tailwind, Astryx reset/components, and the generated Dotrix themes are loaded once through that shared entry. The official `@astryxdesign/core/tailwind-theme.css` bridge follows the themes. Product compatibility aliases follow it, without redefining the bridge's text, surface, status, radius, or spacing roles.

The web app, admin, and public site compile that entry with `@tailwindcss/vite`. The desktop app uses the web build. The shared `@source` entries discover classes in all three apps and the UI package; interpolated class names still require an explicit static mapping, as with any Tailwind build.

Native control defaults use zero-specificity `:where()` selectors so `.stat`, `.tab`, `.sw`, and other control compositions can supply their own padding and backgrounds. Do not add broad, high-specificity native-button resets to the components layer or use `!important` to repair individual controls.

## Tailwind usage

Use layout utilities and Astryx semantic roles together:

```tsx
<section className="rounded-lg border border-border bg-surface p-3 text-primary">
  Content
</section>
```

- `text-primary` and `text-secondary` are text roles; `bg-surface`, `bg-body`, and `bg-muted` are surfaces.
- `bg-accent-bg` with `text-on-accent` is an accent-filled action. `text-accent` is an accent link. Do not use `text-primary` as an accent alias.
- `bg-success` is a strong status fill; `text-success` reads the status text role. The bridge also maps status border/ring roles.
- `rounded-sm`, `rounded-md`, and `rounded-lg` resolve to Astryx inner, element, and container radii. Spacing uses Astryx's four-pixel unit.
- Existing `text-muted-foreground`, `bg-background`, sidebar, and chart aliases remain supported for compatibility.
- `md` uses the app's 900px shell breakpoint. Knowledge changes to its two-column document layout at `sm` (640px).

The bridge uses `@theme reference inline`: it generates utilities referencing active tokens without overwriting them at runtime. Saved accents, dark mode, and portal themes remain owned by `DesignProvider` and the generated themes. Keep existing token names distinct from Astryx's semantic tokens when adding aliases.

## Responsive composition

- Toolbars must size to their wrapped content and must not shrink inside full-height flex pages.
- On phones, Knowledge switches between document browsing and a full-width reader. Settings uses a grouped section picker.
- Sample and live coding sessions use the same session-header layout. Keep pane actions named and keep the agent identity Kai.
- Use one composer surface; native input slots inside the composer preserve issue-picking and follow-up behavior without nested field borders.
- Chat and Codes keep the model control inside the bottom-right footer, before Send/Stop. New sessions allow model selection; existing sessions show the pinned model. Missing models and locally managed models have an explicit disabled state instead of disappearing.
- Composers rest as a compact pill and expand into an input row above the controls while focused, holding a draft, or displaying a menu. New-session screens reserve this first editing row so blur does not move project choices during a click.
- Modes, approvals, runtime and environment choices are inside the plus menu, with the current mode marked on reopening. No mode selector or mode chip sits outside that menu.
- Chat and Codes hide the session sidebar completely with the panel icon and restore it from the conversation header. The desktop preference persists, and the narrow-screen list overlays the main view without discarding drafts.
- The composer action uses a custom icon-only button trigger in the bottom-left footer, alongside the send button. Its menu opens below the plus button; the composer reserves space while open so the menu stays in the viewport without flipping upward.
- In the combined AppShell/TopNav mobile layout, the workspace switch belongs in TopNav's heading as well as SideNav's header; drawer-content mode omits the SideNav header. Workspace selection matches by ID, with a legacy-name fallback limited to old saved sample data.
- Pending-work notices on Home stay in document flow; the agent launcher belongs in the global toolbar, away from page actions.
- The task drawer opts into Astryx's `experimental.isFullWidthOnMobile` at the pinned version. Recheck that option when upgrading the library.

## Verification

`apps/web/e2e/astryx-integration.spec.ts` covers computed control styles, theme-backed Tailwind utilities, mobile Knowledge/toolbar layout, sample Codes and Models, Settings navigation, Home notices, and mobile task details. It runs with the existing presentation suite:

```sh
pnpm --filter @dotrix/web e2e:design
pnpm --filter @dotrix/ui theme:check
pnpm design:audit
pnpm build
pnpm typecheck
pnpm test
```

These browser checks use sample or synthetic API data. They do not exercise production credentials or paid-model behavior.
