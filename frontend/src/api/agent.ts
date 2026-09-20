import api from "./index";

/** 人工介入的待裁决内容，由 Reviewer 质检不通过时产生。 */
export interface AgentInterrupt {
  type: string;
  question: string;
  draft: string;
  feedback: string;
  options: string[];
}

export interface AgentRunStartData {
  run_id: string;
  status: string;
  interrupt?: AgentInterrupt | null;
}

export interface AgentRunStep {
  node_name: string;
  attempt: number;
  input_summary: string | null;
  output_summary: string | null;
  status: string; // running / success / failed
  error_message: string | null;
  duration_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentRunDetail {
  run: {
    run_id: string;
    session_id: string;
    question: string;
    final_answer: string | null;
    status: string;
    error_message: string | null;
    checkpoint_id: string | null;
    retry_count: number;
    started_at: string | null;
    completed_at: string | null;
  };
  steps: AgentRunStep[];
}

export interface AgentRunListItem {
  run_id: string;
  session_id: string;
  question: string;
  status: string;
  retry_count: number;
  started_at: string | null;
  completed_at: string | null;
}

export function startAgentRun(
  question: string,
  sessionId: string = "default"
): Promise<{ data: AgentRunStartData }> {
  return api.post("/agent/runs", { question, session_id: sessionId });
}

export function resumeAgentRun(
  runId: string,
  decision?: string
): Promise<{ data: AgentRunStartData }> {
  return api.post("/agent/runs/resume", { run_id: runId, decision });
}

export function fetchRunDetail(
  runId: string
): Promise<{ data: AgentRunDetail }> {
  return api.get(`/agent/runs/${runId}`);
}

export function listAgentRuns(
  sessionId: string = "default",
  limit: number = 20
): Promise<{ data: AgentRunListItem[] }> {
  return api.get("/agent/runs", { params: { session_id: sessionId, limit } });
}

// ---------------------------------------------------------------------------
// SSE 流式执行（fetch + ReadableStream）
// ---------------------------------------------------------------------------

export interface SSEEvent {
  type: string;
  run_id?: string;
  node?: string;
  output_summary?: string;
  answer?: string;
  message?: string;
  retry_count?: number;
  /** type 为 interrupt 时携带待裁决内容。 */
  interrupt?: AgentInterrupt;
}

const TOKEN_KEY = "rag_token";

/**
 * 发起 SSE 请求，边读边回调。
 *
 * 用法：
 *   await streamAgentRun({
 *     question: "...",
 *     sessionId: "default",
 *     onEvent: (evt) => { ... },
 *     onDone: () => { ... },
 *     onError: (err) => { ... },
 *   });
 */
export async function streamAgentRun(params: {
  question: string;
  sessionId?: string;
  onEvent: (evt: SSEEvent) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  const resp = await fetch("/api/v1/agent/runs/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question: params.question,
      session_id: params.sessionId ?? "default",
    }),
    signal: params.signal,
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`SSE 请求失败: ${resp.status}`);
  }

  await consumeSSE(resp.body, params.onEvent);
  params.onDone?.();
}

/**
 * SSE resume 端点。
 *
 * 传 decision 表示这是在回答人工介入：accept 采纳当前草稿，rewrite 让
 * Generator 按 Reviewer 的反馈重写。不传则按 checkpoint 继续执行。
 */
export async function streamAgentResume(params: {
  runId: string;
  decision?: string;
  onEvent: (evt: SSEEvent) => void;
  onDone?: () => void;
  onError?: (err: Error) => void;
  signal?: AbortSignal;
}): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  const resp = await fetch("/api/v1/agent/runs/stream/resume", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ run_id: params.runId, decision: params.decision }),
    signal: params.signal,
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`SSE 请求失败: ${resp.status}`);
  }

  await consumeSSE(resp.body, params.onEvent);
  params.onDone?.();
}

/**
 * 消费 ReadableStream，按 SSE 协议 (`data: {...}\n\n`) 解析每行 JSON。
 */
async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (evt: SSEEvent) => void
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // 按 \n\n 分割 SSE 事件
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      // SSE 格式: "data: {json}\n"
      const line = rawEvent
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trim())
        .join("");

      if (!line) continue;
      try {
        const evt = JSON.parse(line) as SSEEvent;
        onEvent(evt);
      } catch {
        // 忽略非 JSON 行
      }
    }
  }
}
