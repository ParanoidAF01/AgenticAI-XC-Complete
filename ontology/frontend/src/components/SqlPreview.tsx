import { useState } from "react";

interface SqlPreviewProps {
  sql: string;
}

export function SqlPreview({ sql }: SqlPreviewProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/60">
      <div className="flex items-center justify-between border-b border-slate-700/60 bg-surface-900/80 px-3 py-2">
        <span className="text-xs font-medium text-slate-300">Generated SQL</span>
        <button
          type="button"
          onClick={copy}
          className="text-xs text-teal-400 transition hover:text-teal-300"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-48 overflow-auto bg-surface-950/80 p-3 font-mono text-[11px] leading-relaxed text-teal-100/90">
        <code>{sql}</code>
      </pre>
    </div>
  );
}
