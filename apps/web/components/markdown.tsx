import { CodeBlock } from "@dotrix/ui/components/code-block";
import { cn } from "@dotrix/ui/lib/utils";
import { Children, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A fenced code block's text and language, from the `<code>` react-markdown puts inside `<pre>`. */
function fenced(children: ReactNode): { code: string; language?: string } {
  const child = Children.toArray(children)[0];
  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) return { code: String(children ?? "") };
  const language = /language-([\w+#.-]+)/.exec(child.props.className ?? "")?.[1];
  return { code: String(child.props.children ?? "").replace(/\n$/, ""), language };
}

/**
 * Markdown from issues, comments, and agents. Raw HTML is not rendered (react-markdown's
 * default), so text written by agents or pasted from docs can't inject markup. Fenced code
 * gets a CodeBlock (language, copy, highlighting).
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div
      className={cn(
        "text-sm leading-relaxed break-words [&_code]:[overflow-wrap:anywhere]",
        "[&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_:not(pre)>code]:bg-muted [&_:not(pre)>code]:rounded [&_:not(pre)>code]:px-1 [&_:not(pre)>code]:py-0.5 [&_code]:font-mono [&_:not(pre)>code]:text-xs",
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
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
          pre: ({ node: _node, children }) => <CodeBlock {...fenced(children)} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
