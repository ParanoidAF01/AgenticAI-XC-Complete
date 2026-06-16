import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  p: ({ children }) => (
    <p className="mb-3 last:mb-0 leading-relaxed text-slate-200">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-white">{children}</strong>
  ),
  em: ({ children }) => <em className="text-slate-300 italic">{children}</em>,
  h1: ({ children }) => (
    <h3 className="mb-2 mt-1 text-base font-semibold text-white">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-2 mt-3 text-sm font-semibold text-white">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-2 mt-3 text-sm font-semibold text-teal-200">{children}</h4>
  ),
  ul: ({ children }) => (
    <ul className="markdown-list mb-3 space-y-2 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="markdown-ordered mb-3 space-y-2 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-slate-300 leading-relaxed [&>p]:mb-0">{children}</li>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-3 border-l-2 border-teal-500/40 pl-3 text-slate-400 italic last:mb-0">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-slate-700/60" />,
  code: ({ className, children }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <code className="block overflow-x-auto rounded-lg bg-surface-950/80 p-3 font-mono text-xs text-teal-100/90">
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-surface-900 px-1.5 py-0.5 font-mono text-xs text-teal-300">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="mb-3 overflow-hidden rounded-xl border border-slate-700/60 last:mb-0">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="mb-4 overflow-hidden rounded-xl border border-slate-700/60 bg-surface-900/40 last:mb-0">
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">{children}</table>
      </div>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="border-b border-slate-700/60 bg-surface-900/80">{children}</thead>
  ),
  tbody: ({ children }) => <tbody className="divide-y divide-slate-800/80">{children}</tbody>,
  tr: ({ children }) => (
    <tr className="transition-colors hover:bg-surface-800/30">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="whitespace-nowrap px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-400">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="whitespace-nowrap px-4 py-2.5 text-sm text-slate-200">{children}</td>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-teal-400 underline decoration-teal-500/30 underline-offset-2 hover:text-teal-300"
    >
      {children}
    </a>
  ),
};

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
