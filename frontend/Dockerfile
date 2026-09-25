# ===== 前端构建镜像 =====
# node 构建 → nginx 托管静态产物

FROM node:22-alpine AS builder
WORKDIR /app

# 依赖缓存层: 先拷依赖清单, 依赖不变则此层缓存复用(改代码不清依赖)
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
# 按锁文件(pnpm-lock v9)固定 pnpm 版本; --store-dir 覆盖 .npmrc 里的宿主机路径
RUN npm install -g pnpm@9 && pnpm install --frozen-lockfile --store-dir=/pnpm-store

# 构建产物
COPY . .
RUN pnpm build

# ===== 运行镜像: nginx 托管静态产物 =====
FROM nginx:latest
COPY --from=builder /app/dist /usr/share/nginx/html
# 覆盖默认配置: SPA 路由 + /api 反向代理到后端 + SSE 透传
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]