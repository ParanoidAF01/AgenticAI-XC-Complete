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
    <form onSubmit={handleSubmit} className="chat-input-form rounded-2xl p-2">
      <textarea
        name="question"
        rows={1}
        placeholder="Ask about policies, premiums, agencies, locations…"
        disabled={disabled || isLoading}
        onKeyDown={handleKeyDown}
        onChange={autoResize}
        className="w-full resize-none bg-transparent px-3 py-2 text-sm focus:outline-none disabled:opacity-50"
      />
      <div className="flex items-center justify-between gap-2 px-2 pb-1 pt-1">
        <p className="chat-input-hint text-[11px]">
          Enter to send · Shift+Enter for new line
        </p>
        <div className="flex gap-2">
          {isLoading && (
            <button
              type="button"
              onClick={onCancel}
              className="chat-btn-cancel rounded-lg px-3 py-1.5 text-xs font-medium"
            >
              Cancel
            </button>
          )}
          <button
            type="submit"
            disabled={disabled || isLoading}
            className="chat-btn-submit rounded-lg px-4 py-1.5 text-xs font-semibold disabled:cursor-not-allowed"
          >
            {isLoading ? "Processing…" : "Ask"}
          </button>
        </div>
      </div>
    </form>
  );
}
