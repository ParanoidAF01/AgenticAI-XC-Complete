import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

const components: Components = {
  table: ({ children }) => (
    <div className="md-table-wrap overflow-x-auto">
      <table>{children}</table>
    </div>
  ),
  ul: ({ children }) => (
    <ul className="markdown-list space-y-2 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="markdown-ordered space-y-2 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="[&>p]:mb-0">{children}</li>,
};

interface MarkdownContentProps {
  content: string;
}

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="markdown-content text-sm">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
