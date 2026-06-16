import { wsUrl } from "../config";
import type { WsMessage } from "../types";

export interface AskViaWebSocketOptions {
  question: string;
  sessionId?: string;
  onProgress?: (message: string) => void;
  signal?: AbortSignal;
}

export function askViaWebSocket({
  question,
  sessionId,
  onProgress,
  signal,
}: AskViaWebSocketOptions): Promise<WsMessage> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl("/ws"));
    let settled = false;

    const finish = (handler: () => void) => {
      if (settled) return;
      settled = true;
      handler();
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close();
      }
    };

    const onAbort = () => {
      finish(() => reject(new Error("Request cancelled.")));
    };

    if (signal?.aborted) {
      onAbort();
      return;
    }

    signal?.addEventListener("abort", onAbort, { once: true });

    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          question,
          session_id: sessionId,
        }),
      );
    };

    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as WsMessage;

        if (payload.type === "progress") {
          onProgress?.(payload.message);
          return;
        }

        if (payload.type === "final" || payload.type === "clarification" || payload.type === "error") {
          finish(() => {
            signal?.removeEventListener("abort", onAbort);
            if (payload.type === "error") {
              reject(new Error(payload.message));
            } else {
              resolve(payload);
            }
          });
        }
      } catch {
        finish(() => {
          signal?.removeEventListener("abort", onAbort);
          reject(new Error("Invalid response from server."));
        });
      }
    };

    socket.onerror = () => {
      finish(() => {
        signal?.removeEventListener("abort", onAbort);
        reject(new Error("WebSocket connection failed."));
      });
    };

    socket.onclose = (event) => {
      if (!settled && !event.wasClean) {
        finish(() => {
          signal?.removeEventListener("abort", onAbort);
          reject(new Error("Connection closed before a response was received."));
        });
      }
    };
  });
}
