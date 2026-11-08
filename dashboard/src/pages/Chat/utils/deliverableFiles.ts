export const DELIVERABLE_KINDS = [
  "image",
  "document",
  "data",
  "code",
  "archive",
  "media",
  "other",
] as const;
export type DeliverableKind = (typeof DELIVERABLE_KINDS)[number];
export const DELIVERY_PAGE_SIZE = 6;

export function deliverableKind(file: {
  name: string;
  media_type: string;
}): DeliverableKind {
  const mime = file.media_type.toLowerCase().split(";")[0];
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (
    mime.startsWith("image/") ||
    /^(png|jpe?g|gif|webp|avif|svg|bmp|ico|tiff?|heic)$/.test(ext)
  )
    return "image";
  if (
    /^(audio|video)\//.test(mime) ||
    /^(mp[34]|wav|aac|m4a|flac|ogg|mov|webm|avi|mkv)$/.test(ext)
  )
    return "media";
  if (
    /(zip|compressed|gzip|x-tar|x-bzip|x-7z)/.test(mime) ||
    /^(zip|rar|7z|tar|gz|tgz|bz2|xz)$/.test(ext)
  )
    return "archive";
  if (
    /^(py|ipynb|js|jsx|ts|tsx|css|less|scss|sh|bat|ps1|go|rs|c|h|cpp|java|diff|patch|toml|ya?ml)$/.test(
      ext,
    ) ||
    /(?:javascript|x-python)/.test(mime)
  )
    return "code";
  if (
    /(?:json|csv|tab-separated|spreadsheet|ms-excel|parquet)/.test(mime) ||
    /^(jsonl?|ndjson|csv|tsv|xlsx?|ods|parquet|feather)$/.test(ext)
  )
    return "data";
  if (
    mime.startsWith("text/") ||
    /(?:pdf|word|presentation|rtf|markdown|opendocument.text)/.test(mime) ||
    /^(pdf|docx?|pptx?|md|markdown|txt|rtf|odt|html?)$/.test(ext)
  )
    return "document";
  return "other";
}
