import api from "./index";

export interface User {
  id: number;
  username: string;
  email: string | null;
  is_active: boolean;
  created_at: string;
}

interface LoginResponse {
  access_token: string;
  token_type?: string;
}

export function register(
  username: string,
  password: string,
  email: string | null
): Promise<{ data: { id: number; username: string } }> {
  return api.post("/auth/register", { username, password, email });
}

export function login(
  username: string,
  password: string
): Promise<{ data: LoginResponse }> {
  return api.post("/auth/login", { username, password });
}

export function fetchCurrentUser(): Promise<{ data: User }> {
  return api.get("/auth/me");
}