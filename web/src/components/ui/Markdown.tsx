"use client";

import React from "react";

/**
 * A deliberately small Markdown renderer for the copilot's replies.
 *
 * The model answers in Markdown whatever the prompt says — headings, bold, and
 * especially pipe tables. Rendering that as plain text shows raw asterisks and
 * pipes to the recruiter, so we parse the subset it actually produces:
 * headings, bold, inline code, bullet and numbered lists, pipe tables, and
 * paragraphs. Anything else falls through as text, which is the safe outcome.
 *
 * A full Markdown dependency would also work; this is ~100 lines and keeps the
 * rendering consistent with the rest of the design system.
 */

/** Inline formatting: **bold**, *italic*, `code`. */
function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let i = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${i++}`;

    if (token.startsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-[var(--text-primary)]">
          {token.slice(2, -2)}
        </strong>,
      );
    } else if (token.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-white/8 px-1 py-0.5 font-mono text-[0.85em] text-[var(--accent-soft)]"
        >
          {token.slice(1, -1)}
        </code>,
      );
    } else {
      nodes.push(
        <em key={key} className="italic">
          {token.slice(1, -1)}
        </em>,
      );
    }
    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

const isTableRow = (line: string) => line.trim().startsWith("|") && line.trim().endsWith("|");
const isSeparatorRow = (line: string) => /^\s*\|[\s:|-]+\|\s*$/.test(line);
const cells = (line: string) =>
  line.trim().slice(1, -1).split("|").map((c) => c.trim());

export function Markdown({ content }: { content: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = content.split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    // Pipe table
    if (isTableRow(line) && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) {
      const header = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(cells(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key++} className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-white/10">
                {header.map((cell, c) => (
                  <th key={c} className="px-2 py-1.5 font-medium text-[var(--text-muted)]">
                    {renderInline(cell, `th-${c}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r} className="border-b border-white/[0.06]">
                  {row.map((cell, c) => (
                    <td
                      key={c}
                      className={c > 0 ? "tabular px-2 py-1.5" : "px-2 py-1.5"}
                    >
                      {renderInline(cell, `td-${r}-${c}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      blocks.push(
        <p key={key++} className="text-sm font-semibold text-[var(--text-primary)]">
          {renderInline(heading[2], `h-${key}`)}
        </p>,
      );
      i++;
      continue;
    }

    // Lists
    const isBullet = (l: string) => /^\s*[-*•]\s+/.test(l);
    const isNumbered = (l: string) => /^\s*\d+[.)]\s+/.test(l);
    if (isBullet(line) || isNumbered(line)) {
      const ordered = isNumbered(line);
      const items: string[] = [];
      while (i < lines.length && (ordered ? isNumbered(lines[i]) : isBullet(lines[i]))) {
        items.push(lines[i].replace(/^\s*(?:[-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag key={key++} className="space-y-1">
          {items.map((item, index) => (
            <li key={index} className="flex gap-2">
              <span className="shrink-0 text-[var(--text-muted)]">
                {ordered ? `${index + 1}.` : "•"}
              </span>
              <span>{renderInline(item, `li-${key}-${index}`)}</span>
            </li>
          ))}
        </ListTag>,
      );
      continue;
    }

    // Paragraph — consume until a blank line or the start of another block.
    const paragraph: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !isTableRow(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !isBullet(lines[i]) &&
      !isNumbered(lines[i])
    ) {
      paragraph.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="leading-relaxed">
        {renderInline(paragraph.join(" "), `p-${key}`)}
      </p>,
    );
  }

  return <div className="space-y-2.5">{blocks}</div>;
}
