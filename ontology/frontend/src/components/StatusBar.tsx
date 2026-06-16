import { useEffect, useState } from "react";
import { fetchHealth } from "../api/client";
import type { HealthResponse } from "../types";

function ServiceDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-400">
      <span
        className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]" : "bg-rose-500"}`}
        aria-hidden
      />
      {label}
    </span>
  );
}

export function StatusBar() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const data = await fetchHealth();
        if (active) setHealth(data);
      } catch {
        if (active) setHealth({ status: "unreachable" });
      } finally {
        if (active) setLoading(false);
      }
    };

    load();
    const interval = window.setInterval(load, 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const neo4j = health?.neo4j_connected ?? health?.services?.neo4j ?? false;
  const mssql = health?.mssql_connected ?? health?.services?.mssql ?? false;
  const redis = health?.redis_connected ?? health?.services?.redis ?? false;
  const healthy = health?.status === "healthy";

  return (
    <div className="flex flex-wrap items-center gap-3 border-t border-slate-800/80 bg-surface-900/60 px-4 py-2 text-xs">
      <span
        className={`rounded-full px-2 py-0.5 font-medium ${
          loading
            ? "bg-slate-800 text-slate-400"
            : healthy
              ? "bg-emerald-500/15 text-emerald-300"
              : "bg-amber-500/15 text-amber-300"
        }`}
      >
        {loading ? "Checking services…" : health?.status ?? "unreachable"}
      </span>
      {!loading && health?.status !== "unreachable" && (
        <>
          <ServiceDot ok={neo4j} label="Neo4j" />
          <ServiceDot ok={mssql} label="MSSQL" />
          <ServiceDot ok={redis} label="Redis" />
        </>
      )}
    </div>
  );
}
