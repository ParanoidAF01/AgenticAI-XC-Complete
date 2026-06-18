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
    <div className="data-panel">
      <div className="data-panel__head flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium">Generated SQL</span>
        <button type="button" onClick={copy} className="data-panel__link text-xs">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="data-panel__body-code max-h-48 overflow-auto p-3 font-mono text-[11px] leading-relaxed">
        <code>{sql}</code>
      </pre>
    </div>
  );
}
