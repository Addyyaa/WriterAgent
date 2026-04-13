# WriterAgent Web

`apps/web` 是 WriterAgent 的前端产品层，采用 **Next.js App Router + TypeScript + Tailwind**。

## 目录
- `app`: 路由层（Workspace + Ops Console + BFF Route Handlers）
- `modules`: 业务模块（projects/runs/console/rbac）
- `shared`: 基础 UI 与工具函数
- `server/bff`: BFF 代理与 Cookie 鉴权
- `generated/api`: OpenAPI 生成物与手写类型门面

## 部署与运行

### 1) 安装依赖

```bash
# 在仓库根目录执行
npm install
```

### 2) 配置后端地址

```bash
export BACKEND_BASE_URL='http://127.0.0.1:8000'
```

### 3) 开发模式启动

```bash
npm run web:dev
```

启动后访问：
- `http://127.0.0.1:3000/login`：登录
- `http://127.0.0.1:3000/projects`：项目工作台
- `http://127.0.0.1:3000/runs/<run_id>`：run 实时流页面（WebSocket）
- `http://127.0.0.1:3000/metrics`：专业控制台

### 4) 生产构建

```bash
npm run web:build
```

## 使用说明（BFF + 鉴权）

- 浏览器不直接持有 refresh token，BFF 通过 HttpOnly Cookie 管理：
  - `wa_access`
  - `wa_refresh`
- API 统一通过 `app/api/*` 代理后端，避免前端直接跨域调用后端：
  - `/api/auth/*`
  - `/api/projects`
  - `/api/writing/*`
  - `/api/system/*`
  - `/api/ws-token`
- 当 access token 过期时，BFF 会尝试自动 refresh，再重放一次请求。

## 环境变量

- `BACKEND_BASE_URL`：后端 API 基地址，默认 `http://127.0.0.1:8000`

## OpenAPI 与类型生成

```bash
npm run web:generate:api
```

说明：
- 脚本会从 `${BACKEND_BASE_URL}/openapi.json` 拉取规范。
- 输出到 `apps/web/generated/api/openapi-types.ts`。

## 测试

```bash
npm run web:test
npm --workspace apps/web run lint
npm run web:build
```
