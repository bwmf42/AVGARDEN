# A/GARDEN Frontend

Vue 3 + Vite 前端。生产构建由 `Dockerfile.server` 打包，并由 Go server 在 `31471` 端口提供页面和 API。

## 本地开发

```bash
npm install
npm run dev
```

Vite 默认把页面开在本地开发端口。需要真实数据时，使用项目现有的开发代理或直接访问 NAS 页面；不要在前端代码里写死账号、Token 或生产密钥。

## 验证

```bash
npm test
npm run build
```

- `npm test` 使用 Node 内置测试运行器。
- `npm run build` 输出到 `dist/`，该目录是生成物，不提交。
- 有视觉改动时，还要检查桌面和移动宽度下的空状态、溢出、资源加载和交互。

## 目录

```text
src/api/         API 封装
src/components/  复用组件
src/router/      页面路由
src/views/       媒体库、每日推荐、下载管理、设置等页面
```

视觉规则以 [DESIGN.md](DESIGN.md) 为准；项目和部署规则以根目录 `AGENTS.md` 为准。
