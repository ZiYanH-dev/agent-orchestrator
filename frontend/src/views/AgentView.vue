<script setup lang="ts">
import { onMounted, ref } from "vue";

import { useAgentStore } from "@/stores/agent";

const agentStore = useAgentStore();
const input = ref("");

const nodeLabels: Record<string, string> = {
  planner: "🧠 Planner",
  retriever: "🔍 Retriever",
  generator: "✍️ Generator",
  reviewer: "🧐 Reviewer",
};

const statusColors: Record<string, string> = {
  pending: "#909399",
  planning: "#409eff",
  retrieving: "#409eff",
  generating: "#e6a23c",
  reviewing: "#e6a23c",
  completed: "#67c23a",
  failed: "#f56c6c",
};

async function handleRun() {
  const question = input.value.trim();
  if (!question || agentStore.loading) return;
  input.value = "";
  agentStore.clearCurrent();

  await agentStore.run(question);
}

async function handleResume() {
  if (!agentStore.currentRunId) return;
  await agentStore.resume(agentStore.currentRunId);
}

onMounted(() => {
  agentStore.loadRuns();
});
</script>

<template>
  <div class="agent-view">
    <!-- 顶部：输入区 -->
    <div class="input-area">
      <h3>🤖 多 Agent 协作</h3>
      <p class="hint">Planner → Retriever → Generator ⇄ Reviewer · 流式实时展示 · 故障可恢复</p>
      <div class="input-row">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          placeholder="输入问题，多 Agent 会自动拆解→检索→生成→质检"
          resize="none"
          :disabled="agentStore.loading"
          @keydown.enter.exact.prevent="handleRun"
        />
        <el-button
          type="primary"
          :loading="agentStore.loading"
          :disabled="!input.trim()"
          @click="handleRun"
        >
          {{ agentStore.loading ? "执行中..." : "启动" }}
        </el-button>
      </div>
    </div>

    <!-- 运行状态 -->
    <div v-if="agentStore.currentRunId || agentStore.loading" class="run-status">
      <div class="status-header">
        <span v-if="agentStore.currentRunId" class="run-id">Run ID: {{ agentStore.currentRunId }}</span>
        <span
          class="status-badge"
          :style="{ backgroundColor: statusColors[agentStore.currentRun?.status ?? 'running'] }"
        >
          {{ agentStore.currentRun?.status ?? 'running' }}
        </span>
        <span v-if="agentStore.currentRun?.retry_count" class="retry-info">
          🔁 已恢复 {{ agentStore.currentRun.retry_count }} 次
        </span>
        <el-button
          v-if="agentStore.currentRun?.status === 'failed'"
          type="warning"
          size="small"
          :loading="agentStore.loading"
          @click="handleResume"
        >
          从 Checkpoint 恢复
        </el-button>
      </div>

      <!-- 流式时间线 -->
      <div class="timeline-wrapper">
        <div
          v-for="(step, idx) in agentStore.steps"
          :key="idx"
          class="step-item"
          :class="`step-${step.status}`"
        >
          <div class="step-dot" :class="`dot-${step.status}`">
            <span v-if="step.status === 'running'" class="pulse"></span>
            <span v-else-if="step.status === 'success'" class="check">✓</span>
            <span v-else-if="step.status === 'failed'" class="cross">✕</span>
          </div>
          <div class="step-body">
            <div class="step-title">
              <span class="node-name">{{ nodeLabels[step.node_name] || step.node_name }}</span>
              <span class="attempt">#{{ step.attempt }}</span>
              <span class="step-status" :class="`status-${step.status}`">
                {{ step.status }}
              </span>
            </div>
            <div v-if="step.status === 'running'" class="step-detail running-detail">
              ⏳ 执行中...
            </div>
            <div v-if="step.output_summary && step.status === 'success'" class="step-detail output">
              📤 {{ step.output_summary }}
            </div>
          </div>
          <div v-if="idx < agentStore.steps.length - 1" class="step-connector"></div>
        </div>
      </div>

      <!-- 最终答案（流式展示） -->
      <div v-if="agentStore.currentRun?.final_answer" class="final-answer">
        <div class="answer-label">🎯 最终答案</div>
        <div class="answer-content">{{ agentStore.currentRun.final_answer }}</div>
      </div>
      <div v-else-if="agentStore.loading" class="final-answer pending">
        <div class="answer-label">⏳ 等待最终答案...</div>
      </div>

      <!-- 错误信息 -->
      <div v-if="agentStore.error" class="error-box">
        ❌ {{ agentStore.error }}
      </div>
    </div>

    <!-- 历史运行列表 -->
    <div v-if="agentStore.runs.length > 0 && !agentStore.loading && !agentStore.currentRunId" class="history">
      <h4>📜 历史运行</h4>
      <div
        v-for="run in agentStore.runs"
        :key="run.run_id"
        class="history-item"
        @click="agentStore.currentRunId = run.run_id; agentStore.refreshDetail()"
      >
        <span>{{ run.question }}</span>
        <span class="status-tag" :class="`tag-${run.status}`">{{ run.status }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-view {
  padding: 24px;
  background-color: #f2f3f5;
  min-height: calc(100vh - 56px);
}

.input-area {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}

.input-area h3 {
  margin: 0 0 4px 0;
}

.input-area .hint {
  color: #909399;
  font-size: 13px;
  margin: 0 0 12px 0;
}

.input-row {
  display: flex;
  gap: 12px;
}

.input-row .el-input {
  flex: 1;
}

.input-row .el-button {
  align-self: flex-end;
  height: 54px;
  padding: 0 24px;
}

.run-status {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
}

.status-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.run-id {
  font-family: monospace;
  color: #606266;
  font-size: 13px;
}

.status-badge {
  color: #fff;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: bold;
  text-transform: uppercase;
}

.retry-info {
  color: #e6a23c;
  font-size: 13px;
}

/* Timeline: 自己实现的竖向时间线 */
.timeline-wrapper {
  display: flex;
  flex-direction: column;
  gap: 0;
  margin-bottom: 20px;
  padding-left: 8px;
}

.step-item {
  position: relative;
  padding-bottom: 16px;
}

.step-item:last-child {
  padding-bottom: 0;
}

.step-dot {
  position: absolute;
  left: -8px;
  top: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
  z-index: 1;
}

.dot-running {
  background: #409eff;
  color: #fff;
}

.dot-success {
  background: #67c23a;
  color: #fff;
}

.dot-failed {
  background: #f56c6c;
  color: #fff;
}

.pulse {
  width: 8px;
  height: 8px;
  background: #fff;
  border-radius: 50%;
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.7); }
}

.step-connector {
  position: absolute;
  left: 1px;
  top: 20px;
  width: 2px;
  height: calc(100% - 4px);
  background: #e4e7ed;
  z-index: 0;
}

.step-item:last-child .step-connector {
  display: none;
}

.step-body {
  margin-left: 20px;
  background: #fafbfc;
  border-radius: 6px;
  padding: 10px 14px;
}

.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.node-name {
  font-weight: bold;
  font-size: 15px;
}

.attempt {
  color: #909399;
  font-size: 12px;
}

.step-status {
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 3px;
}

.step-status.status-running { background: #ecf5ff; color: #409eff; }
.step-status.status-success { background: #f0f9eb; color: #67c23a; }
.step-status.status-failed  { background: #fef0f0; color: #f56c6c; }

.step-detail {
  font-size: 13px;
  color: #606266;
}

.step-detail.running-detail {
  color: #409eff;
  font-style: italic;
}

.step-detail.output {
  color: #67c23a;
}

.final-answer {
  background: #f0f9eb;
  border-left: 3px solid #67c23a;
  padding: 12px 16px;
  border-radius: 4px;
}

.final-answer.pending {
  background: #f4f4f5;
  border-left-color: #909399;
}

.answer-label {
  font-weight: bold;
  margin-bottom: 8px;
}

.error-box {
  background: #fef0f0;
  border-left: 3px solid #f56c6c;
  padding: 12px 16px;
  border-radius: 4px;
  color: #f56c6c;
  margin-top: 12px;
}

.history h4 {
  margin: 0 0 12px 0;
}

.history-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  padding: 12px 16px;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.history-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.status-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #f2f3f5;
  color: #606266;
}

.status-tag.tag-completed { background: #f0f9eb; color: #67c23a; }
.status-tag.tag-failed    { background: #fef0f0; color: #f56c6c; }
.status-tag.tag-running   { background: #ecf5ff; color: #409eff; }
</style>
