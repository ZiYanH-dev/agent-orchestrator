<script setup lang="ts">
import { ArrowDown } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const navItems = [
  { path: "/chat", label: "问答" },
  { path: "/agent", label: "多 Agent" },
  { path: "/documents", label: "文档" },
];

function go(path: string) {
  router.push(path);
}

function goProfile() {
  router.push("/profile");
}

function handleLogout() {
  authStore.logout();
  ElMessage.success("已退出登录");
  router.push("/login");
}
</script>

<template>
  <header class="app-header">
    <div class="brand">RAG Agent</div>
    <nav class="nav">
      <button
        v-for="item in navItems"
        :key="item.path"
        class="nav-item"
        :class="{ active: route.path === item.path }"
        @click="go(item.path)"
      >
        {{ item.label }}
      </button>
    </nav>
    <div class="user-area">
      <el-dropdown trigger="click" @command="goProfile">
        <span class="user-trigger">
          <span class="username">{{ authStore.user?.username }}</span>
          <el-icon class="el-icon--right"><arrow-down /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">个人设置</el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 56px;
  background-color: #ffffff;
  border-bottom: 1px solid #e4e7ed;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.brand {
  font-size: 18px;
  font-weight: 600;
  color: #409eff;
}

.nav {
  display: flex;
  gap: 12px;
}

.nav-item {
  padding: 6px 16px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #606266;
  cursor: pointer;
  transition: all 0.2s;
}

.nav-item:hover {
  background-color: #f5f7fa;
}

.nav-item.active {
  background-color: #ecf5ff;
  color: #409eff;
  font-weight: 500;
}

.user-area {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
}

.user-trigger:hover {
  color: #409eff;
}

.username {
  font-size: 14px;
}
</style>
