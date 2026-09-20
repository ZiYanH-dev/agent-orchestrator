import { defineStore } from "pinia";
import { ref } from "vue";

import {
  fetchCurrentUser,
  login as loginApi,
  register as registerApi,
  type User,
} from "@/api/auth";

const TOKEN_KEY = "rag_token";
const USER_KEY = "rag_user";

export const useAuthStore = defineStore("auth", () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) || "");
  const user = ref<User | null>(
    JSON.parse(localStorage.getItem(USER_KEY) || "null")
  );

  function setToken(value: string) {
    token.value = value;
    if (value) {
      localStorage.setItem(TOKEN_KEY, value);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  }

  function setUser(value: User | null) {
    user.value = value;
    if (value) {
      localStorage.setItem(USER_KEY, JSON.stringify(value));
    } else {
      localStorage.removeItem(USER_KEY);
    }
  }

  async function login(username: string, password: string) {
    const res = await loginApi(username, password);
    const accessToken = res.data?.access_token;
    if (!accessToken) {
      throw new Error("登录响应缺少访问令牌");
    }
    setToken(accessToken);
    const me = await fetchCurrentUser();
    setUser(me.data);
    return me.data;
  }

  async function register(
    username: string,
    password: string,
    email: string | null
  ) {
    const res = await registerApi(username, password, email);
    return res.data;
  }

  function logout() {
    setToken("");
    setUser(null);
  }

  return {
    token,
    user,
    login,
    register,
    logout,
  };
});