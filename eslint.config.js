// Gate de qualidade (P0 residual da AGENT-AUDIT.md, item 3).
// Recommended sem type-checking para manter o lint rápido no CI; regras
// type-aware podem ser promovidas depois, deliberadamente, não por default.
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist/", "node_modules/", "sal-intelligence-os/", "api/dist/"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      // `raw?: unknown` e payloads de API externa são legítimos; proibir `any` explícito continua valendo.
      "@typescript-eslint/no-explicit-any": "error",
      // Vars não usadas com prefixo _ são convenção aceita para descarte deliberado.
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    languageOptions: { globals: { process: "readonly", console: "readonly" } },
  },
);
