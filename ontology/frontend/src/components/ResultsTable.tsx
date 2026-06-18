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
      <p className="detail-badge rounded-lg px-3 py-2 text-xs">
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
    <div className="data-panel">
      <div className="data-panel__head flex items-center justify-between px-3 py-2">
        <span className="text-xs font-medium">
          {rows.length} row{rows.length === 1 ? "" : "s"}
        </span>
        {rows.length > 10 && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="data-panel__link text-xs"
          >
            {expanded ? "Show less" : `Show all ${rows.length}`}
          </button>
        )}
      </div>
      <div className="max-h-64 overflow-auto">
        <table className="data-table min-w-full text-left text-xs">
          <thead className="sticky top-0">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className="whitespace-nowrap px-3 py-2 font-mono font-medium"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, index) => (
              <tr key={index}>
                {columns.map((col) => (
                  <td
                    key={col}
                    className="max-w-[220px] truncate whitespace-nowrap px-3 py-2 font-mono"
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
