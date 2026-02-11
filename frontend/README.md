# Audit RAG Frontend

基于 React + Vite + TypeScript 的前端控制台，用于调用本仓库 `api_server.py` 暴露的接口。

## 启动

1. 启动后端（默认 `http://localhost:8000`）
2. 在本目录安装依赖并启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认地址：`http://localhost:5173`

## 代理说明

`vite.config.ts` 已配置代理：

- `/api/*` -> `http://localhost:8000/*`

因此前端代码统一请求 `/api` 前缀，不需要额外处理 CORS。

## 页面能力

- 系统状态：展示 `/info` 和 `/documents/stats` 数据
- 文件上传入库：调用 `/upload_store`，展示新增/跳过/更新统计
- 检索与问答：调用 `/search_with_intent` 与 `/ask`
- 文档管理：列表过滤、文档详情、分块查看、删除文档

## 目录结构

```text
frontend/
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── vite.config.ts
└── src/
    ├── api/
    │   ├── client.ts            # 通用 fetch 与错误处理
    │   └── rag.ts               # 业务 API 封装
    ├── components/
    │   ├── SystemPanel.tsx      # 系统状态面板
    │   ├── UploadPanel.tsx      # 上传入库面板
    │   ├── SearchPanel.tsx      # 检索/问答面板
    │   └── DocumentsPanel.tsx   # 文档管理面板
    ├── types/
    │   └── rag.ts               # 后端响应类型定义
    ├── App.tsx
    ├── main.tsx
    ├── styles.css
    └── vite-env.d.ts
```

## 可扩展点

- 增加鉴权时，在 `src/api/client.ts` 统一注入 token
- 多环境 API 地址可通过 `.env` 覆盖代理策略
- 如需路由化可引入 `react-router-dom`，把 4 个面板拆为独立页面
