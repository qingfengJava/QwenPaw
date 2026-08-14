/**
 * MarkdownView — renders assistant markdown with GFM tables, fenced code
 * highlighting and a copy button per code block. Mirrors the backend chat
 * rendering stack (react-markdown + remark-gfm + syntax highlighter) while
 * keeping the XianWork visual tokens.
 */
import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
// Register only the common languages — the full Prism build costs ~700KB
// in the chat chunk; light registration keeps the exe bundle lean.
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";

const LANGS = new Set<string>();
const LANGUAGE_ALIASES: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  py: "python",
  sh: "bash",
  shell: "bash",
  html: "markup",
  xml: "markup",
  md: "markdown",
  yml: "yaml",
};
for (const [name, mod] of Object.entries({
  javascript,
  typescript,
  jsx,
  tsx,
  python,
  json,
  bash,
  sql,
  markup,
  css,
  markdown,
  yaml,
  java,
  go,
  rust,
})) {
  SyntaxHighlighter.registerLanguage(name, mod as Parameters<typeof SyntaxHighlighter.registerLanguage>[1]);
  LANGS.add(name);
  const alias = LANGUAGE_ALIASES[name];
  if (alias) {
    LANGS.add(alias);
  }
}

function CopyButton({ getText }: { getText: () => string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="md-code-copy"
      onClick={() => {
        void navigator.clipboard.writeText(getText()).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      <i className={`fa-regular ${copied ? "fa-check" : "fa-copy"}`} />
      {copied ? "已复制" : "复制"}
    </button>
  );
}

interface MarkdownViewProps {
  text: string;
}

const MarkdownView = memo(function MarkdownView({ text }: MarkdownViewProps) {
  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre({ children }) {
            return <>{children}</>;
          },
          code({ className, children, ...props }) {
            const raw = String(children ?? "").replace(/\n$/, "");
            const match = /language-(\w+)/.exec(className ?? "");
            const isBlock = raw.includes("\n") || Boolean(match);
            if (!isBlock) {
              return (
                <code className="md-code-inline" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <div className="md-code-block">
                <div className="md-code-bar">
                  <span className="md-code-lang">{match?.[1] ?? "text"}</span>
                  <CopyButton getText={() => raw} />
                </div>
                <SyntaxHighlighter
                  language={(() => {
                    const raw2 = match?.[1] ?? "";
                    const resolved = LANGUAGE_ALIASES[raw2] ?? raw2;
                    return LANGS.has(resolved) ? resolved : "markup";
                  })()}
                  style={oneLight}
                  customStyle={{
                    margin: 0,
                    borderRadius: "0 0 8px 8px",
                    fontSize: 13,
                    background: "#fafafa",
                  }}
                >
                  {raw}
                </SyntaxHighlighter>
              </div>
            );
          },
          a({ children, href }) {
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});

export default MarkdownView;
