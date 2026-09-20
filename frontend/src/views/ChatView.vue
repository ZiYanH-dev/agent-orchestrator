<script setup lang="ts">
import { ChatLineRound, Delete, Edit, Plus } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { nextTick, onMounted, ref, watch } from "vue";

import ChatMessage from "@/components/ChatMessage.vue";
import { useChatStore } from "@/stores/chat";

const chatStore = useChatStore();
const input = ref("");
const messagesContainer = ref<HTMLElement | null>(null);
const editingId = ref<string | null>(null);
const editingName = ref("");

async function handleSend() {
  const question = input.value.trim();
  if (!question || chatStore.loading) return;
  input.value = "";
  await chatStore.sendMessage(question);
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

async function handleDelete() {
  if (!chatStore.currentSessionId) return;
  try {
    await ElMessageBox.confirm("确定删除当前会话？", "提示", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
    await chatStore.deleteCurrentSession();
    ElMessage.success("已删除");
  } catch {
    // 用户取消
  }
}

function startRename(id: string, name: string) {
  editingId.value = id;
  editingName.value = name;
}

async function commitRename() {
  if (!editingId.value || !editingName.value.trim()) {
    editingId.value = null;
    return;
  }
  await chatStore.renameCurrentSession(editingName.value.trim());
  editingId.value = null;
}

watch(
  () => chatStore.messages.length,
  async () => {
    await nextTick();
    messagesContainer.value?.scrollTo({
      top: messagesContainer.value.scrollHeight,
      behavior: "smooth",
    });
  }
);

onMounted(async () => {
  await chatStore.loadSessions();
  // 自动选中第一个会话
  if (chatStore.sessions.length > 0) {
    await chatStore.selectSession(chatStore.sessions[0].id);
  }
});
</script>

<template>
  <div class="chat-layout">
    <!-- 侧边栏：会话列表 -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <el-button type="primary" size="small" @click="chatStore.newSession()">
          <el-icon><Plus /></el-icon>
          新对话
        </el-button>
      </div>

      <div class="session-list">
        <div
          v-for="s in chatStore.sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === chatStore.currentSessionId }"
          @click="chatStore.selectSession(s.id)"
        >
          <template v-if="editingId === s.id">
            <input
              v-model="editingName"
              class="rename-input"
              @click.stop
              @keyup.enter="commitRename"
              @keyup.esc="editingId = null"
              @blur="commitRename"
              ref="editInputRef"
            />
          </template>
          <template v-else>
            <span class="session-name">{{ s.name }}</span>
            <div class="session-actions" @click.stop>
              <el-icon size="14" @click="startRename(s.id, s.name)"><Edit /></el-icon>
            </div>
          </template>
        </div>
        <div v-if="chatStore.sessions.length === 0" class="empty-hint">
          暂无会话，点击上方"新对话"开始
        </div>
      </div>

      <div class="sidebar-footer">
        <el-button
          v-if="chatStore.currentSessionId"
          size="small"
          text
          type="danger"
          @click="handleDelete"
        >
          <el-icon><Delete /></el-icon>
          删除当前
        </el-button>
      </div>
    </aside>

    <!-- 主区：对话 -->
    <main class="chat-main">
      <div ref="messagesContainer" class="messages">
        <template v-if="chatStore.messages.length === 0">
          <div class="empty-welcome">
            <h2>👋 你好，上传文档后开始提问吧</h2>
            <p>我会基于你的知识库回答问题</p>
          </div>
        </template>
        <ChatMessage
          v-for="(msg, index) in chatStore.messages"
          :key="index"
          :message="msg"
        />
        <div v-if="chatStore.loading" class="loading-indicator">
          <el-icon class="is-loading"><ChatLineRound /></el-icon>
          <span>AI 正在思考...</span>
        </div>
      </div>

      <div class="input-area">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          placeholder="输入问题，按 Enter 发送，Shift+Enter 换行"
          resize="none"
          @keydown="handleKeydown"
        />
        <el-button
          type="primary"
          :loading="chatStore.loading"
          :disabled="!input.trim()"
          @click="handleSend"
        >
          发送
        </el-button>
      </div>
    </main>
  </div>
</template>

<style scoped>
.chat-layout {
  display: flex;
  height: calc(100vh - 56px);
  background-color: #f2f3f5;
}

/* 侧边栏 */
.sidebar {
  width: 240px;
  background: #1f1f1f;
  color: #e0e0e0;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 16px 12px;
  border-bottom: 1px solid #333;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 8px 8px 8px;
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  margin-bottom: 4px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.15s;
}

.session-item:hover {
  background: #2a2a2a;
}

.session-item.active {
  background: #333;
  color: #fff;
}

.session-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-actions {
  display: none;
  gap: 4px;
  color: #888;
}

.session-item:hover .session-actions {
  display: flex;
}

.session-actions .el-icon:hover {
  color: #fff;
}

.rename-input {
  width: 100%;
  background: #2a2a2a;
  border: none;
  border-radius: 4px;
  padding: 4px 8px;
  color: #fff;
  font-size: 14px;
  outline: none;
}

.empty-hint {
  padding: 16px;
  font-size: 13px;
  color: #666;
  text-align: center;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #333;
}

/* 主区 */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.empty-welcome {
  text-align: center;
  margin-top: 80px;
  color: #606266;
}

.empty-welcome h2 {
  font-size: 20px;
  margin-bottom: 8px;
}

.loading-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  color: #909399;
  font-size: 14px;
}

.input-area {
  display: flex;
  gap: 12px;
  padding: 16px 24px 24px;
  background-color: #ffffff;
  border-top: 1px solid #e4e7ed;
}

.input-area .el-input {
  flex: 1;
}

.input-area .el-button {
  align-self: flex-end;
  height: 54px;
  padding: 0 24px;
}
</style>
