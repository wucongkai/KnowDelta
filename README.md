# KnowDelta

给定 B 站链接或本地视频，生成带原视频截图、字幕证据和时间戳的图文笔记。

当前版本提供 **React 网页 + FastAPI API + 独立 Celery Worker**，支持视频导入、后台生成、个人笔记库、视频对照阅读与图文导出。原 Python 命令行继续可用。

## 启动网页开发版

需要 Python 3.11+（推荐 3.12）、Node.js 24、pnpm 11、uv 和 Docker。以下命令从仓库根目录执行：

```bash
cp .env.example .env
uv sync --locked --extra web --extra asr --group dev
docker compose up -d postgres redis
uv run alembic -c backend/alembic.ini upgrade head
# 可选：把本地已生成的 CLI 笔记加入笔记库
uv run knowdelta-import
```

分别在三个终端启动：

```bash
# 终端 1：API
uv run knowdelta-api

# 终端 2：视频处理 Worker（macOS 使用 solo，避免原生音视频库 fork 冲突）
uv run celery -A knowdelta.web.worker:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO

# 终端 3：前端
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

打开 [学习工作台](http://127.0.0.1:5174/)。[API 文档](http://127.0.0.1:8000/docs)由 FastAPI 自动生成。前端通过 `/api` 代理调用后端；修改后端源码后重启 API 和 Worker。

- 不配置模型即可使用「原文整理」；文字、视觉模型配置见下文。改完 `.env` 后重启 API 和 Worker。
- 笔记库提供搜索、状态筛选、网格/列表；阅读页提供截图放大、原始转写、段落时间回跳和专注模式。
- 取消只停止本次任务，保留已经成功的阶段；失败与取消任务均可重试。进度按处理阶段展示。
- 网页的本地上传支持视频及可选字幕；默认 2 GiB 视频、10 MiB 字幕。处理完成后可对照原视频。
- 分享时使用「完整图文包 ZIP」；单独下载的 Markdown/HTML 仍引用 `assets/` 图片目录。
- 本版本面向**本机单人使用**，没有账号和权限系统。默认端口仅监听回环地址。

### 完整容器版

```bash
docker compose -f compose.yaml -f compose.app.yaml up --build -d
```

打开 [容器版工作台](http://127.0.0.1:8080/)。这个组合使用独立的 `knowdelta-container` 项目和数据卷，不与开发版数据库或素材混用；前端由 Nginx 提供静态文件并代理 API，API 和 Worker 是独立容器。首次构建需要下载镜像与依赖，首次 ASR 需要下载模型。此配置只开放本机 8080 端口。

```bash
# 查看处理日志 / 停止容器（保留数据卷）
docker compose -f compose.yaml -f compose.app.yaml logs -f worker
docker compose -f compose.yaml -f compose.app.yaml down
```

架构、设计取舍及参考项目见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。整体产品规划见 [DEVELOPMENT.md](DEVELOPMENT.md)。

## 命令行用法

## 安装

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。已在 macOS Apple Silicon / Python 3.12 上验证。

```bash
uv sync --locked --extra asr
```

`asr` 是无字幕时使用的本地语音识别依赖。如果始终提供字幕，可以只运行 `uv sync --locked`。

FFmpeg 优先使用 `KNOWDELTA_FFMPEG`，其次系统 PATH，最后使用依赖自带的 FFmpeg。首次使用语音识别会下载模型，默认 `small`，CPU / int8 推理。模型默认缓存在输出根目录的 `models/` 下；已有 `HF_HOME` 配置时沿用它。

也可以使用 Python 虚拟环境安装：`python -m pip install -e '.[asr]'`；该方式按 pyproject.toml 的版本范围解析，复现锁定版本请使用 uv。

## 先跑通一个视频

不配置模型服务时，使用原文整理模式：

```bash
uv run knowdelta 'https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1' --extractive
```

这个模式保留字幕或转写原句、按时间分段、插入候选截图。**它不做模型摘要，也不声称图片与正文已经通过视觉核验。** 适合先检查素材获取和转写质量。

技术视频可以提供术语提示，提高转写正确拼写的机会：

```bash
uv run knowdelta 'https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1' \
  --extractive --asr-model small \
  --asr-prompt 'MySQL、SQL、InnoDB、MyISAM、B+树、存储引擎'
```

使用本地视频和字幕：

```bash
uv run knowdelta --video /path/to/lesson.mp4 \
  --subtitles /path/to/lesson.srt --extractive
```

字幕支持 SRT、WebVTT 和 B 站 `{"body":[{"from":0,"to":2,"content":"…"}]}` JSON。`--subtitles` 也可覆盖 B 站视频的字幕；`--force-asr` 忽略已有字幕并走语音识别分支。

## 用模型提炼笔记

把 `.env.example` 复制为 `.env`，填写你选择的模型服务：

```dotenv
KNOWDELTA_LLM_BASE_URL=https://your-provider.example/v1
KNOWDELTA_LLM_MODEL=your-text-model
KNOWDELTA_LLM_API_KEY=your-key
KNOWDELTA_VISION_MODEL=your-vision-model
```

以上地址和模型名是占位符。接口需要兼容 `POST {BASE_URL}/chat/completions`、支持 `response_format: {"type":"json_object"}`。支持无密钥的本地模型服务；远程地址要求 HTTPS。

```bash
# 模型根据字幕划分主题、整理正文；配图仍按时间匹配
uv run knowdelta 'https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1'

# 结合实际截图选图、生成图注
uv run knowdelta 'https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1' --vision
```

`--vision` 要求模型支持 base64 图片输入。可在同一基础地址上单独指定 `KNOWDELTA_VISION_MODEL`，否则复用文字模型；章节划分仍使用文字模型。每章发送最多 6 张候选图、选择最多 3 张。文字模式将字幕发送到配置的服务；视觉模式还发送候选截图。密钥仅从环境或当前目录 `.env` 读取，不写入缓存和导出包。

## 输出和重试

命令结束会打印 HTML、Markdown、ZIP 的绝对路径：

```text
data/jobs/<source-key>/
├── source.json             # 标题、作者、分P和来源
├── transcript.json         # 带时间戳的字幕/转写
├── frames.json             # 候选截图索引
├── chapters.json           # 章节与字幕ID映射
├── status.json             # 当前阶段与状态
├── last_run_usage.json     # 模型模式下本次实际调用的 token 用量
├── media/                  # 本地媒体、音频和字幕
├── assets/                 # 原视频候选截图
├── cache/                  # 各阶段、各章节成功结果
└── exports/<note-version>/
    ├── note.html
    ├── note.md
    ├── note.json
    ├── transcript.json
    ├── sources.json
    ├── assets/
    └── note.zip
```

- 打开 `note.html` 即可阅读；分享或移动时使用整个导出目录或解压 `note.zip`。
- 图片使用相对路径；导出包不含原视频、模型缓存或 Cookie。
- 每段正文保留字幕 ID，图片只能引用已经存在的截图 ID。程序检查时间范围和引用，但这不等于自动证明每句话都正确。
- B 站来源链接保留分 P 和秒数；具体客户端是否自动跳转取决于 B 站播放器。本地视频输出可回查的时间标签，不把本机绝对路径放进导出内容。
- 同一命令重跑会复用视频、转写、截图及已生成章节。修改模型或 `--vision` 不会重新下载和转写；修改采样参数会重新抽帧。
- 未完成的阶段不写成功缓存。模型输出无效、来源错误或中途失败后，可重跑同一命令。已有生成结果按内容版本保留。
- 同一视频的任务使用文件锁避免并发写入。平台视频缓存视为本次素材快照；需要重新抓取平台更新后的内容时，换一个 `--output` 目录。

## 参数与平台获取

```bash
uv run knowdelta --help
```

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| `--language` | `zh` | 字幕语言与语音识别语言 |
| `--asr-model` | `small` | 本地 Whisper 模型名或目录 |
| `--asr-prompt` | 空 | 额外术语提示；默认还使用视频标题 |
| `--chapter-seconds` | `180` | 章节分析单批时间上限；还限制字符数和字幕条数 |
| `--frame-interval` | `5` | 周期性截图间隔秒数 |
| `--max-frames` | `180` | 筛选后候选图上限 |
| `--max-duration` | `7200` | 视频时长上限（秒） |
| `--max-size-mb` | `2048` | 媒体大小限制（MiB） |
| `--output` | `data/jobs` | 素材、缓存及结果根目录 |
| `--cookies` | 空 | 用户自行提供的 Netscape 格式 Cookie 文件 |

支持普通 BV/av 视频链接、`p` 分 P、`b23.tv` 短链接；一次只处理一个分 P。链接中的跟踪参数会移除。不支持合集批处理、番剧付费权限获取和直播。

B 站部分字幕或视频需要登录；平台获取失败时，可自行提供 Cookie：

```bash
uv run knowdelta 'https://www.bilibili.com/video/BV…/?p=1' \
  --cookies /private/path/bilibili-cookies.txt --extractive
```

不自动读取浏览器登录态。Cookie 文件不要提交到 Git。无可用字幕时尝试 ASR；如果视频本身无法下载，需稍后重试或使用 `--video` 提供本地素材。下载选用最高 720p 的可用视频优先；大小检查包含下载器限制和最终文件检查，下载器未知体积的媒体可能在完成后才被拒绝。

## 实现边界

- 字幕检查包括空内容、异常时间、明显缺段、乱码和异常重复。时间覆盖是启发式规则，长时间静音可能触发不必要的转写；不声称可以自动判断全部字幕错误。
- 抽帧结合周期采样和采样画面差异；清晰度、感知哈希与局部像素差异共同筛选。分析最多约 3600 个时刻，短暂出现的内容可能漏掉，文字密集画面也可能需要更高分辨率。
- 当前没有独立 OCR 引擎。`--vision` 直接使用视觉模型理解所选截图；无视觉模型时，不推断图表数据或界面含义。
- 长视频按有上限的字幕批次分析主题，每批内部连续覆盖全部字幕；尚无跨批次章节合并。模型正文是否完整保留关键内容仍需抽样核验。
- ASR 默认本地 CPU 推理，术语仍可能识别错误；保留原始转写，模型笔记作为独立结果。语音识别在独立进程执行，避免 macOS 下 OpenCV/PyAV 原生库冲突。
- 网页目前为本机单人工作区；多人权限、全文检索、在线编辑、批量管理、远程对象存储尚未实现。笔记库当前读取最新 100 条记录。

## 开发与验证

```bash
uv sync --locked --extra web --extra asr --group dev
uv run pytest -q
uv run ruff check src backend tests
uv run ruff format --check src backend tests

# Python schema 改动后重新生成 API 契约
uv run python backend/export_openapi.py
cd frontend
pnpm generate:api
pnpm test
pnpm build
pnpm format:check
```

API 和 Worker 启动后，可从仓库根目录运行 `uv run python backend/smoke_web.py`，验证真实上传、队列处理、文件导出、失败重试和取消。该脚本会在当前工作区创建两条验收任务，不调用外部模型。

自动化测试使用程序生成的小视频执行真实解码、抽帧和导出，检查同版式 PPT 不被错误去重、导出可移动、缓存恢复、字幕格式与 ASR 分支、未知引用拒绝、HTML 转义和 URL 校验。模型协议通过 HTTP mock 验证；这不替代真实模型输出质量验收。

上游资料：[yt-dlp](https://github.com/yt-dlp/yt-dlp)、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[FFmpeg](https://ffmpeg.org/)。
