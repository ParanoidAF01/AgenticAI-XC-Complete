import { Header } from "./components/Header";
import { ChatPanel } from "./components/ChatPanel";
import { useChat } from "./hooks/useChat";

export default function App() {
  const {
    messages,
    sessionId,
    isLoading,
    progressMessage,
    sendMessage,
    cancelRequest,
    newSession,
  } = useChat();

  return (
    <div className="flex h-full flex-col bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-surface-800/40 via-surface-950 to-surface-950">
      <Header sessionId={sessionId} onNewSession={newSession} />
      <main className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          progressMessage={progressMessage}
          onSend={sendMessage}
          onCancel={cancelRequest}
        />
      </main>
    </div>
  );
}
