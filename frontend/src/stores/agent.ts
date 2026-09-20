import { defineStore } from "pinia";
import { ref } from "vue";

import {
  fetchRunDetail,
  listAgentRuns,
  streamAgentResume,
  streamAgentRun,
  type SSEEvent,
} from "@/api/agent";

interface StepState {
  node_name: string;
  attempt: number;
  status: "running" | "success" | "failed";
  output_summary?: string;
}

export const useAgentStore = defineStore("agent", () => {
  const currentRunId = ref<string | null>(null);
  const currentRun = ref<{
    run_id: string;
    status: string;
    question: string;
    final_answer: string;
    error_message?: string;
    retry_count: number;
  } | null>(null);
  const steps = ref<StepState[]>([]);
  const loading = ref(false);
  const done = ref(false);
  const error = ref<string | null>(null);
  const runs = ref<
    Array<{
      run_id: string;
      question: string;
      status: string;
      retry_count: number;
    }>
  >([]);

  let abortCtrl: AbortController | null = null;

  async function run(question: string, sessionId: string = "default") {
    // reset
    abortCtrl?.abort();
    abortCtrl = new AbortController();
    loading.value = true;
    done.value = false;
    error.value = null;
    currentRun.value = null;
    steps.value = [];

    try {
      await streamAgentRun({
        question,
        sessionId,
        signal: abortCtrl.signal,
        onEvent: handleEvent,
        onDone: () => {
          loading.value = false;
          done.value = true;
        },
        onError: (err) => {
          error.value = err.message;
          loading.value = false;
        },
      });
    } catch (e) {
      error.value = (e as Error).message;
      loading.value = false;
    }
  }

  async function resume(runId: string) {
    abortCtrl?.abort();
    abortCtrl = new AbortController();
    loading.value = true;
    done.value = false;
    error.value = null;

    try {
      await streamAgentResume({
        runId,
        signal: abortCtrl.signal,
        onEvent: handleEvent,
        onDone: () => {
          loading.value = false;
          done.value = true;
        },
        onError: (err) => {
          error.value = err.message;
          loading.value = false;
        },
      });
    } catch (e) {
      error.value = (e as Error).message;
      loading.value = false;
    }
  }

  function handleEvent(evt: SSEEvent) {
    switch (evt.type) {
      case "node_start": {
        currentRunId.value = evt.run_id ?? currentRunId.value;
        steps.value.push({
          node_name: evt.node!,
          attempt: countAttempt(evt.node!),
          status: "running",
        });
        if (currentRun.value) {
          currentRun.value.status = "running";
        } else if (currentRunId.value) {
          currentRun.value = {
            run_id: currentRunId.value,
            status: "running",
            question: "",
            final_answer: "",
            retry_count: 0,
          };
        }
        break;
      }

      case "node_done": {
        // 找到最后一个同节点 running 的 step，标记为 success
        for (let i = steps.value.length - 1; i >= 0; i--) {
          if (
            steps.value[i].node_name === evt.node &&
            steps.value[i].status === "running"
          ) {
            steps.value[i].status = "success";
            steps.value[i].output_summary = evt.output_summary;
            break;
          }
        }
        break;
      }

      case "final_answer": {
        if (currentRun.value) {
          currentRun.value.final_answer = evt.answer ?? "";
          currentRun.value.status = "completed";
        } else {
          currentRun.value = {
            run_id: evt.run_id ?? "",
            status: "completed",
            question: "",
            final_answer: evt.answer ?? "",
            retry_count: 0,
          };
        }
        currentRunId.value = evt.run_id ?? currentRunId.value;
        break;
      }

      case "error": {
        error.value = evt.message ?? "未知错误";
        if (currentRun.value) {
          currentRun.value.status = "failed";
          currentRun.value.error_message = evt.message;
        }
        break;
      }

      case "resumed": {
        if (currentRun.value) {
          currentRun.value.retry_count = evt.retry_count ?? 0;
          currentRun.value.status = "running";
        }
        break;
      }

      case "done": {
        // stream 正常结束
        break;
      }
    }
  }

  function countAttempt(nodeName: string): number {
    const sameNode = steps.value.filter((s) => s.node_name === nodeName);
    return sameNode.length + 1;
  }

  async function refreshDetail() {
    if (!currentRunId.value) return;
    const res = await fetchRunDetail(currentRunId.value);
    const r = res.data;
    if (r) {
      currentRun.value = {
        run_id: r.run.run_id,
        status: r.run.status,
        question: r.run.question,
        final_answer: r.run.final_answer ?? "",
        error_message: r.run.error_message ?? undefined,
        retry_count: r.run.retry_count,
      };
      steps.value = r.steps.map((s) => ({
        node_name: s.node_name,
        attempt: s.attempt,
        status: s.status as StepState["status"],
        output_summary: s.output_summary ?? undefined,
      }));
    }
  }

  async function loadRuns(sessionId: string = "default") {
    const res = await listAgentRuns(sessionId);
    runs.value = res.data.map((r) => ({
      run_id: r.run_id,
      question: r.question,
      status: r.status,
      retry_count: r.retry_count,
    }));
  }

  function clearCurrent() {
    abortCtrl?.abort();
    abortCtrl = null;
    currentRunId.value = null;
    currentRun.value = null;
    steps.value = [];
    error.value = null;
    done.value = false;
  }

  return {
    currentRunId,
    currentRun,
    steps,
    loading,
    done,
    error,
    runs,
    run,
    resume,
    refreshDetail,
    loadRuns,
    clearCurrent,
  };
});
