// ESLint for the TypeScript apps and packages (Python is Ruff's). Formatting is Prettier's, so
// no style rules here; this catches bugs: unused code, misused hooks, unsafe patterns.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/dist-*/**",
      "**/build/**",
      "**/.next/**",
      "**/node_modules/**",
      "**/.turbo/**",
      "**/playwright-report/**",
      "**/test-results/**",
      "packages/api-client/src/schema.ts",
      ".venv/**",
      ".claude/**",
      "apps/**/.venv/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,js,mjs,cjs}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" }],
      // Gr8r's code runs actions as `cond && act()` and `a ? b() : c()`.
      "@typescript-eslint/no-unused-expressions": ["error", { allowShortCircuit: true, allowTernary: true }],
    },
  },
);
