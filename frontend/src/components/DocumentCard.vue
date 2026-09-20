<script setup lang="ts">
import { Delete } from "@element-plus/icons-vue";
import type { Document } from "@/api/document";

const props = defineProps<{
  document: Document;
}>();

const emit = defineEmits<{
  (e: "delete", id: number): void;
}>();

function onDelete() {
  emit("delete", props.document.id);
}
</script>

<template>
  <div class="document-card">
    <div class="info">
      <div class="filename">{{ document.filename }}</div>
      <div class="meta">
        ID: {{ document.id }} · {{ document.chunk_count || 0 }} 个片段
      </div>
    </div>
    <el-button type="danger" size="small" :icon="Delete" circle @click="onDelete" />
  </div>
</template>

<style scoped>
.document-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background-color: #ffffff;
  transition: box-shadow 0.2s;
}

.document-card:hover {
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.filename {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
  margin-bottom: 4px;
}

.meta {
  font-size: 12px;
  color: #909399;
}
</style>
