"use client";

import * as React from "react";

/** One coloured run of a line: its text and both themes' colours (`--shiki-light`, `--shiki-dark`). */
export interface HighlightToken {
  content: string;
  style?: Record<string, string>;
}

const MAX_CHARS = 300_000; // bigger files stay plain: highlighting them would hold the page up
const MAX_LINES = 8_000;

const NAMES: Record<string, string> = { dockerfile: "dockerfile", makefile: "make", "cmakelists.txt": "cmake", gemfile: "ruby", rakefile: "ruby" };

/** Shiki's language for a file, from its name or extension ("src/a.tsx" → "tsx"); undefined when it has none. */
export function languageOf(path: string): string | undefined {
  const name = path.split("/").pop()?.toLowerCase() ?? "";
  if (NAMES[name]) return NAMES[name];
  if (name.startsWith(".env")) return "dotenv";
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1) : undefined;
}

/**
 * A text's lines as coloured tokens (Shiki, light and dark themes), for code shown with its own line numbers: a file,
 * or one side of a diff. Shiki loads when first needed; until it's done, and for languages it doesn't know or text
 * too big to be worth it, this is null and the text shows plain.
 */
export function useHighlight(text: string, language: string | undefined): HighlightToken[][] | null {
  const [result, setResult] = React.useState<{ text: string; language?: string; lines: HighlightToken[][] } | null>(null);
  React.useEffect(() => {
    if (!language || !text || text.length > MAX_CHARS || text.split("\n").length > MAX_LINES) return;
    let cancelled = false;
    void (async () => {
      try {
        const shiki = await import("shiki");
        if (!(language in shiki.bundledLanguages) && !(language in shiki.bundledLanguagesAlias)) return;
        // Shiki reads the text as data; the tokens carry only its text and colours.
        const { tokens } = await shiki.codeToTokens(text, {
          lang: language as never,
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: false,
        });
        if (!cancelled)
          setResult({
            text,
            language,
            lines: tokens.map((line) => line.map((t) => ({ content: t.content, style: t.htmlStyle as Record<string, string> | undefined }))),
          });
      } catch {
        // Highlighting is a nicety: plain text stays.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [text, language]);
  return result && result.text === text && result.language === language ? result.lines : null;
}
