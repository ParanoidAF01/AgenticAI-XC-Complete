interface ProgressIndicatorProps {
  message: string;
}

export function ProgressIndicator({ message }: ProgressIndicatorProps) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-teal-500/20 bg-teal-500/5 px-4 py-3">
      <div className="relative mt-0.5 h-4 w-4 shrink-0">
        <span className="absolute inset-0 animate-ping rounded-full bg-teal-400/40" />
        <span className="relative block h-4 w-4 rounded-full bg-teal-400/80" />
      </div>
      <div>
        <p className="text-sm font-medium text-teal-200">Working on your question</p>
        <p className="mt-0.5 text-xs text-teal-100/70">{message}</p>
      </div>
    </div>
  );
}
