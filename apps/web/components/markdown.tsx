import { Code, Outline } from "@dotrix/ui/astryx";
import { CodeBlock } from "@dotrix/ui/components/code-block";
import { cn } from "@dotrix/ui/lib/utils";
import { Children, isValidElement, useEffect, useId, useRef, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A fenced code block's text and language, from the `<code>` react-markdown puts inside `<pre>`. */
function fenced(children: ReactNode): { code: string; language?: string } {
  const child = Children.toArray(children)[0];
  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) return { code: String(children ?? "") };
  const language = /language-([\w+#.-]+)/.exec(child.props.className ?? "")?.[1];
  return { code: String(child.props.children ?? "").replace(/\n$/, ""), language };
}

/** "[S1]" outside code becomes a link to "#cite-S1", which `cite` may render (an inline citation). */
function linkCitations(text: string): string {
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/)
    .map((part, i) => (i % 2 ? part : part.replace(/\[(S\d+)\](?![([:])/g, "[$1](#cite-$1)")))
    .join("");
}

/**
 * Markdown from issues, comments, and agents. Raw HTML is not rendered (react-markdown's
 * default), so text written by agents or pasted from docs can't inject markup. Fenced code
 * gets a CodeBlock (language, copy, highlighting). `onCode` may turn inline code into a button
 * (a file path that opens the file): it returns what a click does, or nothing to leave it as text. `cite` turns a
 * source label in the text ("[S1]") into an inline citation; a label it doesn't know stays as written.
 */
export function Markdown({
  children,
  className,
  onCode,
  cite,
  outline = false,
}: {
  children: string;
  className?: string;
  outline?: boolean;
  onCode?: (code: string) => (() => void) | undefined;
  cite?: (label: string) => ReactNode | undefined;
}) {
  const prefix = useId().replace(/:/g, "");
  const content = useRef<HTMLDivElement>(null);
  const [headings, setHeadings] = useState<{ id: string; label: string; level: number }[]>([]);
  useEffect(() => {
    if (!outline) return;
    setHeadings(
      Array.from(content.current?.querySelectorAll<HTMLElement>("h1,h2,h3,h4,h5,h6") ?? []).map((heading) => ({
        id: heading.id,
        label: heading.textContent ?? "",
        level: Number(heading.tagName.slice(1)),
      })),
    );
  }, [children, outline]);
  return (
    <>
      {outline && headings.length > 2 && (
        <details className="document-outline">
          <summary>On this page</summary>
          <Outline items={headings} label="On this page" density="compact" />
        </details>
      )}

      <div
        ref={content}
        className={cn(
          "text-sm leading-relaxed break-words",
          "[&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
          "[&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:text-sm [&_h3]:font-medium",
          "[&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:my-0.5",
          "[&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_table]:text-xs [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1",
          "[&_input[type=checkbox]]:mr-1.5 [&>*+*]:mt-2",
          className,
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            ...(outline
              ? Object.fromEntries(
                  ["h1", "h2", "h3", "h4", "h5", "h6"].map((tag) => [
                    tag,
                    ({ node, children: label }: { node?: { position?: { start: { offset?: number } } }; children?: ReactNode }) => {
                      const id = `${prefix}-heading-${node?.position?.start.offset ?? 0}`;
                      switch (tag) {
                        case "h1":
                          return <h1 id={id}>{label}</h1>;
                        case "h2":
                          return <h2 id={id}>{label}</h2>;
                        case "h3":
                          return <h3 id={id}>{label}</h3>;
                        case "h4":
                          return <h4 id={id}>{label}</h4>;
                        case "h5":
                          return <h5 id={id}>{label}</h5>;
                        default:
                          return <h6 id={id}>{label}</h6>;
                      }
                    },
                  ]),
                )
              : {}),
            a: ({ node: _node, ...props }) => {
              const label = props.href?.startsWith("#cite-") ? props.href.slice(6) : null;
              if (label) return cite?.(label) ?? <>[{label}]</>;
              return <a {...props} target="_blank" rel="noreferrer noopener" />;
            },
            pre: ({ node: _node, children }) => <CodeBlock {...fenced(children)} />,
            code: ({ node: _node, className: codeClass, children: code, ...props }) => {
              const text = String(code ?? "");
              const click = !codeClass && !text.includes("\n") ? onCode?.(text) : undefined;
              return click ? (
                <button type="button" className="path-link" onClick={click} data-tip="Open in Files">
                  <Code color="inherit">{text}</Code>
                </button>
              ) : (
                <Code className={codeClass} {...props} color="primary">
                  {code}
                </Code>
              );
            },
          }}
        >
          {cite ? linkCitations(children) : children}
        </ReactMarkdown>
      </div>
    </>
  );
}
