<script setup lang="ts">
import { Lock, User } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const route = useRoute();

const authStore = useAuthStore();
const activeTab = ref("login");
const loginForm = ref<{ username: string; password: string }>({ username: "", password: "" });
const registerForm = ref<{ username: string; password: string; email: string }>({ username: "", password: "", email: "" });
const loading = ref(false);

async function handleLogin() {
  if (loading.value) return;
  loading.value = true;
  try {
    await authStore.login(loginForm.value.username, loginForm.value.password);
    ElMessage.success("登录成功");
    const redirect =
      typeof route.query.redirect === "string" ? route.query.redirect : "/chat";
    router.push(redirect);
  } catch (err) {
    ElMessage.error(`登录失败：${err instanceof Error ? err.message : "未知错误"}`);
  } finally {
    loading.value = false;
  }
}

async function handleRegister() {
  if (loading.value) return;
  loading.value = true;
  try {
    await authStore.register(
      registerForm.value.username,
      registerForm.value.password,
      registerForm.value.email || null
    );
    ElMessage.success("注册成功，请登录");
    loginForm.value.username = registerForm.value.username;
    loginForm.value.password = "";
    activeTab.value = "login";
  } catch (err) {
    ElMessage.error(`注册失败：${err instanceof Error ? err.message : "未知错误"}`);
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-view">
    <div class="login-card">
      <h1 class="title">RAG Agent 登录</h1>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="登录" name="login">
          <el-form label-position="top" @submit.prevent="handleLogin">
            <el-form-item label="用户名">
              <el-input
                v-model="loginForm.username"
                :prefix-icon="User"
                placeholder="请输入用户名"
              />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="loginForm.password"
                :prefix-icon="Lock"
                type="password"
                show-password
                placeholder="请输入密码"
                @keyup.enter="handleLogin"
              />
            </el-form-item>
            <el-button
              type="primary"
              class="submit-btn"
              :loading="loading"
              @click="handleLogin"
            >
              登录
            </el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="注册" name="register">
          <el-form label-position="top" @submit.prevent="handleRegister">
            <el-form-item label="用户名">
              <el-input
                v-model="registerForm.username"
                :prefix-icon="User"
                placeholder="3-32 位字母数字下划线"
              />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="registerForm.email" placeholder="选填" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input
                v-model="registerForm.password"
                :prefix-icon="Lock"
                type="password"
                show-password
                placeholder="至少 6 位"
                @keyup.enter="handleRegister"
              />
            </el-form-item>
            <el-button
              type="primary"
              class="submit-btn"
              :loading="loading"
              @click="handleRegister"
            >
              注册
            </el-button>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.login-view {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 56px);
  background-color: #f2f3f5;
}

.login-card {
  width: 360px;
  padding: 32px;
  background-color: #ffffff;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.title {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 600;
  text-align: center;
  color: #303133;
}

.submit-btn {
  width: 100%;
}
</style>