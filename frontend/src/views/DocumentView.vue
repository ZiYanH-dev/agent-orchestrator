<script setup lang="ts">
import { Upload } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { onMounted, ref } from "vue";

import DocumentCard from "@/components/DocumentCard.vue";
import { useDocumentStore } from "@/stores/document";

const documentStore = useDocumentStore();
const fileInput = ref<HTMLInputElement | null>(null);

onMounted(() => {
  documentStore.loadDocuments().catch((err) => {
    ElMessage.error(`加载文档失败：${err instanceof Error ? err.message : "未知错误"}`);
  });
});

function triggerUpload() {
  fileInput.value?.click();
}

async function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  target.value = "";

  try {
    await documentStore.upload(file);
    ElMessage.success("上传成功");
  } catch (err) {
    ElMessage.error(`上传失败：${err instanceof Error ? err.message : "未知错误"}`);
  }
}

async function handleDelete(documentId: number) {
  try {
    await ElMessageBox.confirm("确定删除该文档吗？", "提示", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
    await documentStore.remove(documentId);
    ElMessage.success("删除成功");
  } catch (err) {
    if (err !== "cancel") {
      ElMessage.error(`删除失败：${err instanceof Error ? err.message : "未知错误"}`);
    }
  }
}
</script>

<template>
  <div class="document-view">
    <div class="toolbar">
      <h2 class="title">文档管理</h2>
      <input
        ref="fileInput"
        type="file"
        accept=".txt,.pdf,.md,.doc,.docx"
        style="display: none"
        @change="handleFileChange"
      />
      <el-button type="primary" :icon="Upload" @click="triggerUpload">
        上传文档
      </el-button>
    </div>

    <div v-if="documentStore.loading && !documentStore.documents.length" class="loading">
      <el-icon class="is-loading"><Upload /></el-icon>
      <span>加载中...</span>
    </div>

    <div v-else-if="!documentStore.documents.length" class="empty">
      暂无文档，点击右上角上传
    </div>

    <div v-else class="document-list">
      <DocumentCard
        v-for="doc in documentStore.documents"
        :key="doc.id"
        :document="doc"
        @delete="handleDelete"
      />
    </div>
  </div>
</template>

<style scoped>
.document-view {
  padding: 24px;
  min-height: calc(100vh - 56px);
  background-color: #f2f3f5;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.loading,
.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 60px 0;
  color: #909399;
}

.document-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 800px;
}
</style>
