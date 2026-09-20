import { defineStore } from "pinia";
import { ref } from "vue";

import {
  chatStream,
  createSession,
  deleteSession,
  fetchChatHistory,
  listSessions,
  renameSession,
  type SessionOut,
  type Source,
} from "@/api/chat";

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  isError?: boolean;
  streaming?: boolean;
}

function parseSources(raw: unknown): Source[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw as Source[];
  try {
    return JSON.parse(raw as string);
  } catch {
    return [];
  }
}

export const useChatStore = defineStore("chat", () => {
  const sessions = ref<SessionOut[]>([]);
  const currentSessionId = ref<string>("");
  const messages = ref<Message[]>([]);
  const loading = ref(false);

  // ---- Session 管理 ----

  async function loadSessions() {
    try {
      const res = await listSessions();
      sessions.value = (res as unknown as { data: SessionOut[] }).data || [];
    } catch {
      sessions.value = [];
    }
  }

  async function newSession(): Promise<string | null> {
    try {
      const res = await createSession("新对话");
      const session = (res as unknown as { data: SessionOut }).data;
      sessions.value.unshift(session);
      await selectSession(session.id);
      return session.id;
    } catch {
      return null;
    }
  }

  async function selectSession(sessionId: string) {
    currentSessionId.value = sessionId;
    messages.value = [];
    await loadHistory();
  }

  async function renameCurrentSession(name: string) {
    if (!currentSessionId.value) return;
    try {
      const res = await renameSession(currentSessionId.value, name);
      const updated = (res as unknown as { data: SessionOut }).data;
      const idx = sessions.value.findIndex((s) => s.id === updated.id);
      if (idx >= 0) sessions.value[idx] = updated;
    } catch {
      // 忽略重命名错误
    }
  }

  async function deleteCurrentSession() {
    if (!currentSessionId.value) return;
    try {
      await deleteSession(currentSessionId.value);
      sessions.value = sessions.value.filter((s) => s.id !== currentSessionId.value);
      messages.value = [];
      currentSessionId.value = "";
      // 自动选中第一个或创建新的
      if (sessions.value.length > 0) {
        await selectSession(sessions.value[0].id);
      }
    } catch {
      // 忽略删除错误
    }
  }

  // ---- 对话 ----

  async function sendMessage(question: string) {
    // 没有会话先创建
    if (!currentSessionId.value) {
      const id = await newSession();
      if (!id) return;
    }

    const userMessage: Message = { role: "user", content: question };
    messages.value.push(userMessage);

    // 先推一个空 assistant 消息占位，后续流式填充
    const assistantMsg: Message = {
      role: "assistant",
      content: "",
      streaming: true,
    };
    messages.value.push(assistantMsg);
    loading.value = true;

    try {
      await chatStream(question, currentSessionId.value, (event) => {
        switch (event.type) {
          case "sources": {
            assistantMsg.sources = (event.data as Source[]) || [];
            break;
          }
          case "token": {
            assistantMsg.content += event.data as string;
            break;
          }
          case "done": {
            assistantMsg.streaming = false;
            break;
          }
        }
      });
    } catch (err) {
      assistantMsg.streaming = false;
      const errMsg = err instanceof Error ? err.message : "未知错误";
      if (!assistantMsg.content) {
        assistantMsg.content = `错误：${errMsg}`;
        assistantMsg.isError = true;
      }
    } finally {
      loading.value = false;
    }
  }

  async function loadHistory() {
    if (!currentSessionId.value) {
      messages.value = [];
      return;
    }
    try {
      const res = await fetchChatHistory(currentSessionId.value);
      const items = (res as unknown as { data: { items: ChatHistoryItem[] } }).data?.items || [];
      messages.value = items.flatMap((record: ChatHistoryItem) => [
        { role: "user" as const, content: record.question },
        {
          role: "assistant" as const,
          content: record.answer,
          sources: parseSources(record.sources),
        },
      ]);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "未知错误";
      messages.value = [
        {
          role: "assistant",
          content: `加载历史失败：${errMsg}`,
          isError: true,
        },
      ];
    }
  }

  function clearMessages() {
    messages.value = [];
  }

  return {
    sessions,
    currentSessionId,
    messages,
    loading,
    loadSessions,
    newSession,
    selectSession,
    renameCurrentSession,
    deleteCurrentSession,
    sendMessage,
    loadHistory,
    clearMessages,
  };
});

interface ChatHistoryItem {
  question: string;
  answer: string;
  sources?: Source[] | string;
}