<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

const route = useRoute();
const router = useRouter();

// 展示未匹配到的地址，便于用户确认是不是手输错了路径
const attemptedPath = computed<string>(() => route.fullPath);

function goHome(): void {
  // 不带 token 时交给全局前置守卫重定向到 /login，这里不重复判断登录态
  void router.replace("/chat");
}
</script>

<template>
  <div class="not-found-view">
    <div class="code">404</div>
    <h2 class="title">页面不存在</h2>
    <p class="description">你访问的地址没有对应的页面。</p>
    <p class="attempted-path">{{ attemptedPath }}</p>
    <el-button type="primary" @click="goHome">回到首页</el-button>
  </div>
</template>

<style scoped>
.not-found-view {
  min-height: calc(100vh - 56px);
  background-color: #f2f3f5;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
}

.code {
  font-size: 96px;
  font-weight: 700;
  line-height: 1;
  color: #409eff;
  letter-spacing: 4px;
}

.title {
  margin: 24px 0 8px;
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.description {
  margin: 0 0 12px;
  font-size: 14px;
  color: #909399;
}

.attempted-path {
  margin: 0 0 24px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  color: #c0c4cc;
  word-break: break-all;
  max-width: 480px;
  text-align: center;
}
</style>
