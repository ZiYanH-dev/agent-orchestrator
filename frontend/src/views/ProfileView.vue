<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import { fetchCurrentUser, type User } from "@/api/auth";

const user = ref<User | null>(null);
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    const res = await fetchCurrentUser();
    user.value = res.data;
  } catch (err) {
    ElMessage.error(
      `加载用户信息失败：${err instanceof Error ? err.message : "未知错误"}`
    );
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="profile-view">
    <h2 class="page-title">个人设置</h2>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="user" class="profile-card">
      <div class="avatar-section">
        <div class="avatar">{{ user.username.charAt(0).toUpperCase() }}</div>
        <div class="avatar-info">
          <div class="username">{{ user.username }}</div>
          <div class="user-id">ID: {{ user.id }}</div>
        </div>
      </div>

      <el-divider />

      <el-form label-position="left" label-width="100px" class="profile-form">
        <el-form-item label="用户名">
          <el-input :model-value="user.username" disabled />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input :model-value="user.email || '未设置'" disabled />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-tag :type="user.is_active ? 'success' : 'danger'">
            {{ user.is_active ? "正常" : "已禁用" }}
          </el-tag>
        </el-form-item>
        <el-form-item label="注册时间">
          <el-input
            :model-value="new Date(user.created_at).toLocaleDateString('zh-CN')"
            disabled
          />
        </el-form-item>
      </el-form>
    </div>

    <div v-else class="empty">无法加载用户信息</div>
  </div>
</template>

<style scoped>
.profile-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 32px 24px;
  min-height: calc(100vh - 56px);
  background-color: #f2f3f5;
}

.page-title {
  margin: 0 0 24px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.loading,
.empty {
  text-align: center;
  padding: 60px 0;
  color: #909399;
}

.profile-card {
  background-color: #ffffff;
  border-radius: 8px;
  padding: 32px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
}

.avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background-color: #409eff;
  color: #ffffff;
  font-size: 28px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.username {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}

.user-id {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}

.profile-form {
  margin-top: 8px;
}
</style>