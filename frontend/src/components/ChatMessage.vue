<script setup lang="ts">
import type { Message } from "@/stores/chat";

defineProps<{
  message: Message;
}>();
</script>

<template>
  <div
    class="message"
    :class="{
      'message-user': message.role === 'user',
      'message-assistant': message.role === 'assistant',
      'message-error': message.isError,
    }"
  >
    <div class="avatar">{{ message.role === "user" ? "我" : "AI" }}</div>
    <div class="bubble">
      <pre class="content">{{ message.content }}</pre>
      <div v-if="message.sources && message.sources.length" class="sources">
        <div class="sources-title">引用来源：</div>
        <div
          v-for="(source, index) in message.sources"
          :key="index"
          class="source-item"
        >
          {{ index + 1 }}. {{ source.content?.slice(0, 80) || source }}...
          <span v-if="source.score" class="score">
            (score: {{ source.score.toFixed(3) }})
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.message-user {
  flex-direction: row-reverse;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 500;
  color: #fff;
  background-color: #909399;
  flex-shrink: 0;
}

.message-user .avatar {
  background-color: #409eff;
}

.bubble {
  max-width: 70%;
  padding: 12px 16px;
  border-radius: 8px;
  background-color: #f5f7fa;
  color: #303133;
}

.message-user .bubble {
  background-color: #ecf5ff;
}

.message-error .bubble {
  background-color: #fef0f0;
  color: #f56c6c;
}

.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
}

.sources {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #dcdfe6;
  font-size: 12px;
  color: #606266;
}

.sources-title {
  font-weight: 500;
  margin-bottom: 6px;
}

.source-item {
  margin-bottom: 4px;
}

.score {
  color: #909399;
}
</style>
