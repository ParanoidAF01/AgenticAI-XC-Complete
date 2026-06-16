import type { AssistantMetadata } from "../types";
import { ResultsTable } from "./ResultsTable";
import { SqlPreview } from "./SqlPreview";

interface MessageDetailsProps {
  metadata: AssistantMetadata;
}

export function MessageDetails({ metadata }: MessageDetailsProps) {
  const { sql, results, tablesUsed, intent, entities, executionTimeMs } = metadata;

  return (
    <div className="mt-3 space-y-3 border-t border-slate-700/50 pt-3">
      {(intent || executionTimeMs !== undefined) && (
        <div className="flex flex-wrap gap-2">
          {intent && (
            <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-violet-300">
              {intent}
            </span>
          )}
          {executionTimeMs !== undefined && (
            <span className="rounded-md bg-slate-700/50 px-2 py-0.5 text-[11px] text-slate-400">
              {executionTimeMs.toFixed(0)} ms
            </span>
          )}
          {metadata.isClarification && (
            <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-300">
              Needs clarification
            </span>
          )}
        </div>
      )}

      {entities && entities.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {entities.slice(0, 8).map((entity, index) => (
            <span
              key={`${entity.type}-${index}`}
              className="rounded-full border border-slate-700 bg-surface-900/60 px-2 py-0.5 text-[11px] text-slate-400"
            >
              <span className="text-slate-500">{entity.type ?? "Entity"}:</span>{" "}
              {String(entity.resolved ?? entity.value ?? "—")}
            </span>
          ))}
        </div>
      )}

      {tablesUsed && tablesUsed.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            Tables used
          </p>
          <div className="flex flex-wrap gap-1">
            {tablesUsed.map((table) => (
              <span
                key={table}
                className="rounded bg-surface-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-400"
              >
                {table}
              </span>
            ))}
          </div>
        </div>
      )}

      {sql && <SqlPreview sql={sql} />}
      {results && results.length > 0 && <ResultsTable rows={results} />}
    </div>
  );
}
