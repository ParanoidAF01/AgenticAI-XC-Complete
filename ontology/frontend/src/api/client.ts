import { apiUrl } from "../config";
import type { ChatRequest, ChatResponse, HealthResponse } from "../types";

async function parseJson<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : "Request failed. Please try again.";
    throw new Error(detail);
  }
  return data as T;
}

export async function askQuestion(payload: ChatRequest): Promise<ChatResponse> {
  const response = await fetch(apiUrl("/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseJson<ChatResponse>(response);
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(apiUrl("/health"));
  return parseJson<HealthResponse>(response);
}
