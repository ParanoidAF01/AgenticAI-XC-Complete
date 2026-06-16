interface ChatInputProps {
  onSend: (question: string) => void;
  onCancel: () => void;
  isLoading: boolean;
  disabled?: boolean;
}

export function ChatInput({ onSend, onCancel, isLoading, disabled }: ChatInputProps) {
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("question") as HTMLTextAreaElement;
    const value = input.value.trim();
    if (!value) return;
    onSend(value);
    input.value = "";
    input.style.height = "auto";
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  const autoResize = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const el = event.target;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-2xl border border-slate-700/80 bg-surface-800/80 p-2 shadow-xl shadow-black/20 ring-1 ring-white/5 backdrop-blur"
    >
      <textarea
        name="question"
        rows={1}
        placeholder="Ask about policies, premiums, agencies, locations…"
        disabled={disabled || isLoading}
        onKeyDown={handleKeyDown}
        onChange={autoResize}
        className="w-full resize-none bg-transparent px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none disabled:opacity-50"
      />
      <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-1">
        <p className="text-[11px] text-slate-500">
          Enter to send · Shift+Enter for new line
        </p>
        <div className="flex gap-2">
          {isLoading && (
            <button
              type="button"
              onClick={onCancel}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-surface-700 hover:text-white"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={disabled || isLoading}
            className="rounded-lg bg-gradient-to-r from-teal-600 to-cyan-600 px-4 py-1.5 text-xs font-semibold text-white shadow-lg shadow-teal-900/30 transition hover:from-teal-500 hover:to-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isLoading ? "Processing…" : "Ask"}
          </button>
        </div>
      </div>
    </form>
  );
}
