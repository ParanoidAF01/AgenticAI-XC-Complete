import { useMemo, useState } from "react";

interface ResultsTableProps {
  rows: Record<string, unknown>[];
}

export function ResultsTable({ rows }: ResultsTableProps) {
  const [expanded, setExpanded] = useState(false);

  const columns = useMemo(() => {
    if (rows.length === 0) return [];
    const keys = new Set<string>();
    rows.slice(0, 20).forEach((row) => {
      Object.keys(row).forEach((key) => keys.add(key));
    });
    return Array.from(keys);
  }, [rows]);

  const visibleRows = expanded ? rows : rows.slice(0, 10);

  if (rows.length === 0) {
    return (
      <p className="rounded-lg bg-surface-900/60 px-3 py-2 text-xs text-slate-500">
        Query returned no rows.
      </p>
    );
  }

  const formatCell = (value: unknown): string => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  };

  return (
    <div className="overflow-hidden rounded-xl border border-slate-700/60">
      <div className="flex items-center justify-between border-b border-slate-700/60 bg-surface-900/80 px-3 py-2">
        <span className="text-xs font-medium text-slate-300">
          {rows.length} row{rows.length === 1 ? "" : "s"}
        </span>
        {rows.length > 10 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs text-teal-400 hover:text-teal-300"
          >
            {expanded ? "Show less" : `Show all ${rows.length}`}
          </button>
        )}
      </div>
      <div className="max-h-64 overflow-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="sticky top-0 bg-surface-800">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className="whitespace-nowrap border-b border-slate-700/60 px-3 py-2 font-mono font-medium text-slate-400"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr
                key={index}
                className="border-b border-slate-800/80 odd:bg-surface-900/30 hover:bg-surface-800/40"
              >
                {columns.map((col) => (
                  <td
                    key={col}
                    className="max-w-[220px] truncate whitespace-nowrap px-3 py-2 font-mono text-slate-300"
                    title={formatCell(row[col])}
                  >
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
