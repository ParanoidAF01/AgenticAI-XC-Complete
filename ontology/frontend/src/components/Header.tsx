import { StatusBar } from "./StatusBar";

interface HeaderProps {
  sessionId: string;
  onNewSession: () => void;
}

export function Header({ sessionId, onNewSession }: HeaderProps) {
  return (
    <header className="border-b border-slate-800/80 bg-surface-900/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500/20 to-cyan-500/10 ring-1 ring-teal-500/30">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5 text-teal-400"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              aria-hidden
            >
              <circle cx="12" cy="12" r="3" />
              <circle cx="12" cy="5" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="18" cy="16" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="6" cy="16" r="1.5" fill="currentColor" stroke="none" />
              <path d="M12 8v1M15.5 14.5l-1-0.6M8.5 14.5l1-0.6" />
            </svg>
          </div>
          <div>
            <h1 className="text-base font-semibold tracking-tight text-white">
              Ontology Insurance Chat
            </h1>
            <p className="text-xs text-slate-400">
              Natural language → SQL powered by your metadata graph
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className="hidden max-w-[180px] truncate rounded-lg bg-surface-800 px-2.5 py-1 font-mono text-[11px] text-slate-500 sm:inline"
            title={sessionId}
          >
            {sessionId.slice(0, 8)}…
          </span>
          <button
            type="button"
            onClick={onNewSession}
            className="rounded-lg border border-slate-700 bg-surface-800 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:bg-surface-700 hover:text-white"
          >
            New session
          </button>
        </div>
      </div>
      <StatusBar />
    </header>
  );
}
