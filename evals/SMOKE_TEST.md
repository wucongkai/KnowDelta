# 命令行 MVP 验收记录

日期：2026-09-15。环境：macOS Apple Silicon、Python 3.12。

## 自动化检查

- `pytest -q`：33 项通过。
- `ruff check src tests`、`ruff format --check src tests`：通过。
- `uv lock --check --offline`：锁文件与项目配置一致。
- `git diff --check`：通过。
- 使用程序生成的实际视频执行解码、截图、去重、FFmpeg 音轨转换及导出。
- HTTP mock 验证模型请求、视觉图片输入、JSON 解析、限流重试、权限错误、输出截断及模型切换缓存。

## 用户提供的 B 站样本

- 来源：https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1
- 标题：Mysql是什么？架构是怎么样的？
- 作者：小白debug。
- 平台元信息时长约 614.585 秒；下载文件解码时长 614.500 秒。
- 未提供 Cookie；媒体下载成功，未取得可用平台字幕，走本地 ASR。
- 使用 `faster-whisper:small`、CPU/int8，并提供 MySQL 等术语提示。
- 获得 241 条转写片段、154 张候选截图。
- 原文整理输出 4 个时间分段、24 个段落和 7 张不同截图。
- 同时生成 Markdown、HTML、结构化 JSON 和 ZIP。
- 校验全部字幕时间范围、引用的截图文件、ZIP 完整性及独立目录解压后的 HTML 图片路径。
- 再次执行相同命令，视频获取、转写和抽帧均命中缓存，无需联网或重复 ASR。
- 抽样查看原视频截图，画面内容清晰可读。

复现命令（仓库已建立虚拟环境时）：

```bash
.venv/bin/knowdelta 'https://www.bilibili.com/video/BV1p5qhYsE4f/?p=1' \
  --extractive --asr-model small \
  --asr-prompt 'MySQL、SQL、InnoDB、MyISAM、B+树、存储引擎、连接器、解析器、优化器、执行器'
```

本机结果位于 `data/jobs/491e3aeb2c2cd3ca052e/exports/5f05533927ccd1b6008a/`，运行素材与结果不提交 Git。

## 尚未验证与质量限制

- 未提供真实模型服务地址、模型名和密钥，模型摘要及视觉选图仅通过协议 mock 验证，尚无真实模型质量验收。
- 该样本是原文整理模式，图片按时间匹配，不代表语义选图已验证。
- 自动转写仍有错误，例如部分“索引”被识别为“索隐”，不能作为已校对的技术文章直接发布。术语提示提高了部分专有名词的可读性，不能保证逐字准确。
- HTML 的资源、链接与转义通过程序检查；浏览器自动预览被 URL 策略阻止，未完成浏览器视觉验收。
- 目前只实测一个公开视频；分 P、短链、字幕失败等分支通过自动化测试覆盖，不宣称所有 B 站视频均可获取。
