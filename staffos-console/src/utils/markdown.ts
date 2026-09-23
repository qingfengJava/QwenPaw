export interface FrontmatterEntry {
  key: string;
  value: string;
}

export interface ParsedMarkdownFrontmatter {
  body: string;
  entries: FrontmatterEntry[];
}

const FRONTMATTER_PATTERN = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/;

/** Split a leading YAML frontmatter block from the Markdown body. */
export function parseMarkdownFrontmatter(
  content: string,
): ParsedMarkdownFrontmatter {
  const match = FRONTMATTER_PATTERN.exec(content);
  if (!match) return { body: content, entries: [] };

  const entries = match[1]
    .split(/\r?\n/)
    .map((line) => {
      const separator = line.indexOf(":");
      if (separator <= 0 || /^\s/.test(line)) return null;

      return {
        key: line.slice(0, separator).trim(),
        value: line.slice(separator + 1).trim(),
      };
    })
    .filter((entry): entry is FrontmatterEntry => entry !== null);

  return { body: content.slice(match[0].length), entries };
}

/** Remove YAML frontmatter from the beginning of a Markdown string. */
export const stripFrontmatter = (content: string): string =>
  parseMarkdownFrontmatter(content).body;

const HARD_BREAK_SUFFIX = /\s{2,}$/;

/**
 * Turn single line breaks into hard breaks (two trailing spaces).
 *
 * Skill files are often written loosely: code lines directly follow a
 * heading without a fenced block, and strict CommonMark collapses those
 * continuation lines into one paragraph. Appending two trailing spaces
 * preserves the source line structure without touching block semantics.
 * Content inside fenced code blocks is left untouched.
 */
export function hardenSingleBreaks(content: string): string {
  const lines = content.split("\n");
  let inFence = false;
  let fenceMarker = "";
  return lines
    .map((line, index) => {
      const trimmed = line.trim();
      // 围栏块（``` 或 ~~~）内部保持原样
      if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) {
        const marker = trimmed.slice(0, 3);
        if (!inFence) {
          inFence = true;
          fenceMarker = marker;
        } else if (marker.slice(0, fenceMarker.length) === fenceMarker) {
          inFence = false;
          fenceMarker = "";
        }
        return line;
      }
      if (inFence) return line;
      const next = lines[index + 1];
      const nextHasContent = next !== undefined && next.trim().length > 0;
      if (
        line.trim().length > 0 &&
        nextHasContent &&
        !HARD_BREAK_SUFFIX.test(line)
      ) {
        return `${line}  `;
      }
      return line;
    })
    .join("\n");
}
