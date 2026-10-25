/**
 * Defence-in-depth cleanup for Mermaid SVG before it is inserted via
 * dangerouslySetInnerHTML. Mermaid ``securityLevel: "strict"`` already
 * blocks many sinks; this strips residual event handlers and script-protocol
 * links (href / xlink:href) that can survive into the SVG string.
 */

const SCRIPT_PROTOCOL = /^\s*(?:javascript|vbscript|data\s*:\s*text\/html)/i;

function isDangerousUrl(value: string | null): boolean {
  if (value == null) return false;
  return SCRIPT_PROTOCOL.test(value);
}

function stripDangerousAttributes(el: Element): void {
  // Snapshot attributes — NamedNodeMap mutates while we remove.
  const attrs = Array.from(el.attributes);
  for (const attr of attrs) {
    const name = attr.name;
    const lower = name.toLowerCase();
    if (lower.startsWith("on")) {
      el.removeAttribute(name);
      continue;
    }
    if (
      lower === "href" ||
      lower === "xlink:href" ||
      lower.endsWith(":href")
    ) {
      if (isDangerousUrl(attr.value)) {
        el.removeAttribute(name);
      }
    }
  }
}

/**
 * Return a sanitized SVG markup string safe to inject into the chat Markdown
 * renderer. Empty / non-SVG input is returned unchanged.
 */
export function sanitizeMermaidSvg(svg: string): string {
  const trimmed = svg.trim();
  if (!trimmed) return svg;

  // Prefer DOMParser so we do not execute scripts while parsing.
  const parser = new DOMParser();
  const doc = parser.parseFromString(trimmed, "image/svg+xml");
  const parseError = doc.querySelector("parsererror");
  if (parseError) {
    // Fallback: treat as HTML fragment wrapping an <svg>.
    const htmlDoc = parser.parseFromString(trimmed, "text/html");
    const svgEl = htmlDoc.querySelector("svg");
    if (!svgEl) return "";
    return sanitizeSvgElement(svgEl);
  }

  const root =
    doc.documentElement?.tagName?.toLowerCase() === "svg"
      ? doc.documentElement
      : doc.querySelector("svg");
  if (!root) return "";
  return sanitizeSvgElement(root);
}

function sanitizeSvgElement(root: Element): string {
  root.querySelectorAll("script").forEach((node) => node.remove());
  stripDangerousAttributes(root);
  root.querySelectorAll("*").forEach((el) => stripDangerousAttributes(el));
  return root.outerHTML;
}
