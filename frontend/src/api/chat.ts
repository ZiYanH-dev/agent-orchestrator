import api from "./index";

export interface Source {
  content?: string;
  score?: number;
  [key: string]: unknown;
}

export interface ChatResponse {
  answer: string;
  sources?: Source[] | string;
}

export interface ChatHistoryItem {
  question: string;
  answer: string;
  sources?: Source[] | string;
}

export interface SessionOut {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export function listSessions(): Promise<{ data: SessionOut[] }> {
  return api.get("/chat/sessions");
}

export function createSession(name: string = "新对话"): Promise<{ data: SessionOut }> {
  return api.post("/chat/sessions", { name });
}

export function renameSession(sessionId: string, name: string): Promise<{ data: SessionOut }> {
  return api.put(`/chat/sessions/${sessionId}`, { name });
}

export function deleteSession(sessionId: string): Promise<{ data: { deleted: boolean } }> {
  return api.delete(`/chat/sessions/${sessionId}`);
}

export function chat(
  question: string,
  sessionId: string = "default"
): Promise<{ data: ChatResponse }> {
  return api.post("/chat", { question, session_id: sessionId });
}

export function fetchChatHistory(
  sessionId: string = "default"
): Promise<{ data: { items: ChatHistoryItem[] } }> {
  return api.get("/chat/history", { params: { session_id: sessionId } });
}

/** SSE 流式对话（手动 fetch + ReadableStream 解析）。 */
export async function chatStream(
  question: string,
  sessionId: string,
  onEvent: (event: { type: string; data: unknown }) => void,
  signal?: AbortSignal
): Promise<void> {
  const token = localStorage.getItem("rag_token");
  const response = await fetch("/api/v1/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: token ? `Bearer ${token}` : "",
    },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`请求失败: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (payload === "[DONE]") continue;
      try {
        const parsed = JSON.parse(payload);
        onEvent(parsed);
      } catch {
        // 忽略解析错误
      }
    }
  }
}