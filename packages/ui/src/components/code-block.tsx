"use client"

import * as React from "react"
import { CheckIcon, CopyIcon } from "lucide-react"
import { cn } from "@dotrix/ui/lib/utils"
import { Button } from "@dotrix/ui/components/button"

const MAX_HIGHLIGHT_CHARS = 20_000 // longer blocks stay plain: highlighting them isn't worth it
const HIGHLIGHT_DELAY_MS = 150 // while text streams in, wait for a pause before highlighting

type Highlighted = { code: string; html: string }

/**
 * A code block with its language and a copy button. Syntax highlighting (Shiki, light and dark
 * themes) loads only when a code block is first shown, so pages without code don't pay for it;
 * until then, and for languages it doesn't know, the code shows as plain text.
 */
function CodeBlock({ code, language, className }: { code: string; language?: string; className?: string }) {
  const [highlighted, setHighlighted] = React.useState<Highlighted | null>(null)
  const [copied, setCopied] = React.useState(false)
  const lang = language?.toLowerCase()

  React.useEffect(() => {
    if (!lang || code.length > MAX_HIGHLIGHT_CHARS) return
    let cancelled = false
    const timer = window.setTimeout(async () => {
      try {
        const shiki = await import("shiki")
        if (!(lang in shiki.bundledLanguages) && !(lang in shiki.bundledLanguagesAlias)) return
        // Shiki escapes the code itself; the HTML it returns is only its own markup.
        const html = await shiki.codeToHtml(code, {
          lang,
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: false,
        })
        if (!cancelled) setHighlighted({ code, html })
      } catch {
        // Highlighting is a nicety: plain text stays.
      }
    }, HIGHLIGHT_DELAY_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [code, lang])

  React.useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(timer)
  }, [copied])

  async function copy() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      // The clipboard can be unavailable (insecure context, permissions).
    }
  }

  return (
    <div data-slot="code-block" className={cn("bg-muted/60 overflow-hidden rounded-md border text-xs", className)}>
      <div className="text-muted-foreground flex items-center justify-between border-b py-1 pr-1 pl-3">
        <span className="font-mono">{language || "text"}</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-6"
          onClick={() => void copy()}
          aria-label={copied ? "Copied" : "Copy code"}
          title={copied ? "Copied" : "Copy code"}
        >
          {copied ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
        </Button>
      </div>
      {highlighted?.code === code ? (
        <div
          className="code-block-shiki overflow-x-auto p-3 font-mono leading-relaxed [&_pre]:bg-transparent!"
          dangerouslySetInnerHTML={{ __html: highlighted.html }}
        />
      ) : (
        <pre className="overflow-x-auto p-3 font-mono leading-relaxed">
          <code>{code}</code>
        </pre>
      )}
    </div>
  )
}

export { CodeBlock }
