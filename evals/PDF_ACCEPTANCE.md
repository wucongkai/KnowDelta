# PDF 导出验收

日期：2026-10-24。环境：macOS Apple Silicon、Python 3.12、Node 24、WeasyPrint 70.0。

## 已通过

- Python 全量 47 个测试通过，覆盖真实 PDF 渲染、中文字体嵌入、图片、正文提取、无图/长文/高图、资源访问限制、缺图错误、缓存、重试、独立子进程与 API 下载。测试仍有两条上游依赖弃用提示。
- PDF 任务派发失败不会阻断视频任务派发与中断恢复；排版版本变化和文件丢失后不会继续提供旧缓存。
- 前端 3 个 Vitest 测试通过；TypeScript 检查和 Vite 生产构建通过。这些单元测试不替代新增导出菜单的浏览器端到端验收。
- Ruff 检查与格式检查通过。
- 临时 SQLite 数据库执行全部 Alembic 迁移成功，`alembic check` 未发现模型与迁移差异。
- 既有真实笔记「CANN 挑战赛赛题解析」生成 35 页 PDF，17 个章节、34 处图片绘制，文件约 4.64 MiB。输出位于仓库的 `output/pdf/CANN挑战赛赛题解析.pdf`（验收产物不提交 Git）。
- 使用 PDFium 渲染全部 35 页并检查四张联系表，另放大检查第 1、2、3、33、35 页。标题、目录、中文、图片、图注、章节衔接和页码未发现缺失、重叠或截断。
- PDF 从独立输出目录读取并渲染；图片直接保存在 PDF 中，字体嵌入且正文可提取，无需源素材目录或项目服务。生成器资源加载器拒绝外部请求。

## 验证边界与启用步骤

本次沙箱无法连接 Docker socket 与本机 PostgreSQL，因此未执行现有开发库迁移、容器镜像重建或在线服务重启，也未验收真实 Redis → PDF Worker 的整条队列链路。数据库/API 测试使用 SQLite，渲染与子进程使用真实 WeasyPrint。尚未在 macOS 预览及浏览器 PDF 阅读器中逐项操作；上述视觉检查使用 PDFium。

在本机终端按 README 更新依赖，执行 `uv run alembic -c backend/alembic.ini upgrade head`，重启 API 和视频 Worker，再启动新增 PDF Worker。现有环境请保留自己的 `.env`。进入历史笔记，点击「导出笔记 → PDF · 含图片」，验证状态流转、下载与再次打开页面后的缓存恢复。完整容器模式可用 README 中的 Compose 命令重建启动。
