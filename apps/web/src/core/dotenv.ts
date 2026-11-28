/** Environment variables in .env format, for a project's environment: one `KEY=value` per line. Blank lines and
 *  `#` comments are skipped, an `export ` prefix is allowed, and matching quotes around a value are removed. The
 *  server checks the names and values; this only reads the text and says which line it couldn't. */
export type DotenvResult = { variables: Record<string, string>; error?: string };

export function parseDotenv(text: string): DotenvResult {
  const variables: Record<string, string> = {};
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!.trim();
    if (!line || line.startsWith("#")) continue;
    const body = line.startsWith("export ") ? line.slice(7).trimStart() : line;
    const eq = body.indexOf("=");
    const name = eq > 0 ? body.slice(0, eq).trim() : "";
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) return { variables, error: `Line ${i + 1} isn't KEY=value` };
    let value = body.slice(eq + 1).trim();
    if (value.length >= 2 && (value[0] === '"' || value[0] === "'") && value.endsWith(value[0]!)) value = value.slice(1, -1);
    if (name in variables) return { variables, error: `${name} is set twice` };
    variables[name] = value;
  }
  return { variables };
}

export function formatDotenv(variables: Record<string, string>): string {
  return Object.entries(variables)
    .map(([name, value]) => `${name}=${value}`)
    .join("\n");
}
