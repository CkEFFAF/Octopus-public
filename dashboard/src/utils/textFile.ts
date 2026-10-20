/** Text classification is platform independent; content must still be valid UTF-8. */
export function isTextFile(name: string, mediaType = "") {
  const base = name.split(/[\\/]/).pop()?.toLowerCase() ?? "";
  return (
    mediaType.startsWith("text/") ||
    /^(dockerfile|makefile|\.env(?:\..*)?|\.gitignore|\.editorconfig|\.npmrc)$/.test(
      base,
    ) ||
    /\.(txt|md|markdown|json|jsonc|yaml|yml|toml|ini|cfg|conf|csv|tsv|py|pyi|js|jsx|mjs|cjs|ts|tsx|sh|bash|zsh|ps1|psm1|bat|cmd|log|sql|xml|html|css|scss|less|go|rs|java|c|h|cpp|hpp|rb|php|r|vue|svelte)$/.test(
      base,
    )
  );
}

export function decodeUtf8Text(bytes: Uint8Array) {
  const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  if (text.includes("\0"))
    throw new Error("Binary file cannot be displayed as UTF-8");
  return text;
}
