/** Display only: never rewrites a stored or manually chosen title. */
export function previewText(value?: string | null, limit = 96): string {
  const text = (value ?? "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*`#>]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
}

/** Old generated English reports should not overwhelm a Chinese preview. */
export function localizedPreview(value: string | undefined, language: string) {
  const text = previewText(value);
  return language.startsWith("zh") &&
    !/[\u3400-\u9fff]/u.test(text) &&
    ((text.match(/[A-Za-z]+/g)?.length ?? 0) >= 4 || text.includes("_"))
    ? ""
    : text;
}
