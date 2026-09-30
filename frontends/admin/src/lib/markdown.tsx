/**
 * Safe renderer for the small Markdown subset the assistant produces:
 * paragraphs, headings, bullet/numbered lists, **bold**, *italic*, `code`,
 * [links](https://…) and bare URLs. Same rules as the widget's renderer.
 *
 * It builds React elements (never raw HTML), and only http(s) links are
 * rendered as anchors, so model output cannot inject markup or scripts.
 */
import { Fragment, type ReactNode } from "react";

const INLINE_PATTERN =
  /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\((https?:\/\/[^\s)]+)\)|https?:\/\/[^\s<>()]+[^\s<>().,;:!?])/g;

function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function link(key: string, url: string, label: string): ReactNode {
  const href = safeHref(url);
  if (!href) return label;
  return (
    <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow">
      {label}
    </a>
  );
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    const key = `${keyPrefix}-${index++}`;
    if (token.startsWith("**")) nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("`")) nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    else if (token.startsWith("[")) nodes.push(link(key, match[2] ?? "", token.slice(1, token.indexOf("]"))));
    else if (token.startsWith("http")) nodes.push(link(key, token, token));
    else nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

type Block =
  | { kind: "paragraph"; lines: string[] }
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

export function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  for (const rawLine of markdown.replace(/\r\n/g, "\n").split("\n")) {
    const line = rawLine.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    const item = (bullet ?? numbered)?.[1];
    if (!line.trim()) {
      blocks.push({ kind: "paragraph", lines: [] });
    } else if (heading) {
      blocks.push({ kind: "heading", text: heading[1] ?? "" });
    } else if (item !== undefined) {
      const ordered = Boolean(numbered);
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(item);
      else blocks.push({ kind: "list", ordered, items: [item] });
    } else if (last?.kind === "paragraph") {
      last.lines.push(line);
    } else {
      blocks.push({ kind: "paragraph", lines: [line] });
    }
  }
  return blocks.filter((block) => block.kind !== "paragraph" || block.lines.length > 0);
}

/** Render assistant Markdown as safe React elements. */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      {parseBlocks(text).map((block, blockIndex) => {
        const key = `b${blockIndex}`;
        if (block.kind === "heading") return <p key={key} className="md__heading">{renderInline(block.text, key)}</p>;
        if (block.kind === "list") {
          const ListTag = block.ordered ? "ol" : "ul";
          return (
            <ListTag key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInline(item, `${key}-${itemIndex}`)}</li>
              ))}
            </ListTag>
          );
        }
        return (
          <p key={key}>
            {block.lines.map((line, lineIndex) => (
              <Fragment key={`${key}-${lineIndex}`}>
                {lineIndex > 0 && <br />}
                {renderInline(line, `${key}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
