import { ThemeToggle } from "./ThemeToggle";

interface HeaderProps {
  sessionId: string;
  onNewSession: () => void;
  onGoHome: () => void;
}

export function Header({ sessionId, onNewSession, onGoHome }: HeaderProps) {
  return (
    <header className="app-header">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4">
        <button
          type="button"
          onClick={onGoHome}
          aria-label="Back to home"
          className="app-header__home-btn group flex items-center gap-3 text-left"
        >
          <div className="app-header__logo flex h-10 w-10 items-center justify-center rounded-xl transition">
            <svg
              viewBox="0 0 24 24"
              className="h-5 w-5 text-app-text-accent"
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
            <h1 className="app-header__title text-base font-semibold tracking-tight">
              Ontology Insurance Chat
            </h1>
            <p className="app-header__subtitle text-xs">
              Natural language → SQL powered by your metadata graph
            </p>
          </div>
        </button>

        <div className="flex items-center gap-2">
          <span
            className="app-header__session hidden max-w-[180px] truncate rounded-lg px-2.5 py-1 font-mono text-[11px] sm:inline"
            title={sessionId}
          >
            {sessionId.slice(0, 8)}…
          </span>
          <ThemeToggle />
          <button
            type="button"
            onClick={onNewSession}
            className="app-btn-secondary rounded-lg px-3 py-1.5 text-xs font-medium"
          >
            New session
          </button>
        </div>
      </div>
    </header>
  );
}
