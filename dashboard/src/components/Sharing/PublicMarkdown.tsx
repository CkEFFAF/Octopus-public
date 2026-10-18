import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useMathPlugins } from "../Markdown/mathPlugins";
import styles from "../Markdown/index.module.less";

function privateHost(hostname: string): boolean {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, "")
    .replace(/\.$/, "");
  if (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host.endsWith(".local") ||
    (!host.includes(".") && !host.includes(":")) ||
    host === "::" ||
    host === "::1" ||
    (/^f[cd]/.test(host) && host.includes(":")) ||
    (/^fe[89ab]/.test(host) && host.includes(":")) ||
    host.startsWith("::ffff:")
  )
    return true;
  const parts = host.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part)))
    return false;
  const [a, b] = parts;
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    a >= 224 ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    (a === 100 && b >= 64 && b <= 127)
  );
}

function publicHref(href?: string): string | undefined {
  if (!href || !/^https?:\/\//i.test(href)) return undefined;
  try {
    const url = new URL(href);
    if (
      url.username ||
      url.password ||
      privateHost(url.hostname) ||
      /^\/(api|share|chat|workbench|personalization|admin)(\/|$)/i.test(
        decodeURIComponent(url.pathname),
      )
    )
      return undefined;
    return url.href;
  } catch {
    return undefined;
  }
}

/** Public text only: no image requests, private downloads, raw HTML or execution. */
export default function PublicMarkdown({ content }: { content: string }) {
  const math = useMathPlugins(content);
  const remarkPlugins = useMemo(
    () => [remarkGfm, ...math.remarkPlugins],
    [math.remarkPlugins],
  );
  return (
    <div className={styles.markdownBody}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={remarkPlugins}
        rehypePlugins={math.rehypePlugins}
        components={{
          img: () => null,
          a: ({ href, children }) => {
            const safe = publicHref(href);
            return safe ? (
              <a
                href={safe}
                target="_blank"
                rel="noreferrer noopener"
                referrerPolicy="no-referrer"
              >
                {children}
              </a>
            ) : (
              <span>{children}</span>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
