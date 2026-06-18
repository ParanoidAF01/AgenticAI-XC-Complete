interface ProgressIndicatorProps {
  message: string;
}

export function ProgressIndicator({ message }: ProgressIndicatorProps) {
  return (
    <div className="progress-card flex items-start gap-3 rounded-2xl px-4 py-3">
      <div className="relative mt-0.5 h-4 w-4 shrink-0">
        <span className="progress-card__ping absolute inset-0 animate-ping rounded-full" />
        <span className="progress-card__dot relative block h-4 w-4 rounded-full" />
      </div>
      <div>
        <p className="progress-card__title text-sm font-medium">
          Working on your question
        </p>
        <p className="progress-card__sub mt-0.5 text-xs">{message}</p>
      </div>
    </div>
  );
}
