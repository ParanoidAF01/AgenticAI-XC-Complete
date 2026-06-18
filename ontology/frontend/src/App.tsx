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
    <div className="app-shell flex h-full flex-col">
      <Header
        sessionId={sessionId}
        onNewSession={newSession}
        onGoHome={newSession}
      />
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
