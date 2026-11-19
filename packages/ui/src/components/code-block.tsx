import { CodeBlock as AstryxCodeBlock } from "@astryxdesign/core/CodeBlock";

export function CodeBlock({ code, language, className }: { code: string; language?: string; className?: string }) {
  return <AstryxCodeBlock code={code} language={language} className={className} hasCopyButton hasLanguageLabel />;
}
