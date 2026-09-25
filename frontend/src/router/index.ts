import { createRouter, createWebHistory } from "vue-router";

import AgentView from "@/views/AgentView.vue";
import ChatView from "@/views/ChatView.vue";
import DocumentView from "@/views/DocumentView.vue";
import LoginView from "@/views/LoginView.vue";
import NotFoundView from "@/views/NotFoundView.vue";
import ProfileView from "@/views/ProfileView.vue";

const TOKEN_KEY = "rag_token";

const routes = [
  { path: "/", redirect: "/chat" },
  { path: "/login", name: "Login", component: LoginView },
  {
    path: "/chat",
    name: "Chat",
    component: ChatView,
    meta: { requiresAuth: true },
  },
  {
    path: "/agent",
    name: "Agent",
    component: AgentView,
    meta: { requiresAuth: true },
  },
  {
    path: "/documents",
    name: "Documents",
    component: DocumentView,
    meta: { requiresAuth: true },
  },
  {
    path: "/profile",
    name: "Profile",
    component: ProfileView,
    meta: { requiresAuth: true },
  },
  // 404 兜底必须放在最后：vue-router 按数组顺序匹配，通配路由提前会吃掉后面所有路径
  {
    path: "/:pathMatch(.*)*",
    name: "NotFound",
    component: NotFoundView,
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (to.meta.requiresAuth && !token) {
    return { path: "/login", query: { redirect: to.fullPath } };
  }
  if (to.path === "/login" && token) {
    return { path: "/chat" };
  }
});

export default router;
