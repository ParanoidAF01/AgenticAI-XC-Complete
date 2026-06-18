import type { AssistantMetadata } from "../types";
import { ResultsTable } from "./ResultsTable";
import { SqlPreview } from "./SqlPreview";

interface MessageDetailsProps {
  metadata: AssistantMetadata;
}

export function MessageDetails({ metadata }: MessageDetailsProps) {
  const { sql, results, tablesUsed, entities, executionTimeMs } = metadata;

  return (
    <div className="msg-details-divider mt-3 space-y-3 border-t pt-3">
      {(executionTimeMs !== undefined || metadata.isClarification) && (
        <div className="flex flex-wrap gap-2">
          {executionTimeMs !== undefined && (
            <span className="detail-badge rounded-md px-2 py-0.5 text-[11px]">
              Query ran in {executionTimeMs.toFixed(0)} ms
            </span>
          )}
          {metadata.isClarification && (
            <span className="detail-warning rounded-md px-2 py-0.5 text-[11px]">
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
              className="detail-chip rounded-full px-2 py-0.5 text-[11px]"
            >
              <span className="detail-chip__label">{entity.type ?? "Entity"}:</span>{" "}
              {String(entity.resolved ?? entity.value ?? "—")}
            </span>
          ))}
        </div>
      )}

      {tablesUsed && tablesUsed.length > 0 && (
        <div>
          <p className="detail-chip__label mb-1 text-[11px] font-medium uppercase tracking-wide">
            Tables used
          </p>
          <div className="flex flex-wrap gap-1">
            {tablesUsed.map((table) => (
              <span
                key={table}
                className="detail-badge rounded px-1.5 py-0.5 font-mono text-[10px]"
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
