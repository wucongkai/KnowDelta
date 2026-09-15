import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import __version__
from .pipeline import Options, run
from .storage import PipelineError


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("必须大于 0")
    return result


def positive_float(value: str) -> float:
    result = float(value)
    if not 0 < result < float("inf"):
        raise argparse.ArgumentTypeError("必须是大于 0 的有限数字")
    return result


def language_code(value: str) -> str:
    if not re.fullmatch("[a-z]{2,3}", value):
        raise argparse.ArgumentTypeError("请使用 zh、en 等语言代码")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="B 站 / 本地视频 → 带来源的图文笔记")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("url", nargs="?", help="B 站视频地址，支持 p 分 P 和 b23.tv")
    result.add_argument("--video", type=Path, help="本地视频路径，与 URL 二选一")
    result.add_argument("--subtitles", type=Path, help="可选 SRT / VTT / B站 JSON 字幕")
    result.add_argument("--output", type=Path, default=Path("data/jobs"), help="任务数据根目录")
    result.add_argument("--cookies", type=Path, help="可选 Netscape 格式 Cookie 文件")
    result.add_argument(
        "--language", type=language_code, default="zh", help="字幕/转写语言，默认 zh"
    )
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--extractive", action="store_true", help="无需模型：原文按时间分段和配图")
    modes.add_argument("--vision", action="store_true", help="将候选截图发送给视觉模型选图")
    result.add_argument("--force-asr", action="store_true", help="忽略现有字幕，重新进行语音识别")
    result.add_argument("--asr-prompt", default="", help="可选转写术语提示，例如 MySQL、InnoDB")
    result.add_argument(
        "--asr-model", default="small", help="faster-whisper 模型名或目录，默认 small"
    )
    result.add_argument(
        "--chapter-seconds", type=positive_int, default=180, help="单批字幕最长秒数"
    )
    result.add_argument(
        "--frame-interval", type=positive_float, default=5, help="周期性候选截图间隔秒数"
    )
    result.add_argument("--max-frames", type=positive_int, default=180, help="候选截图数量上限")
    result.add_argument(
        "--max-duration", type=positive_int, default=7200, help="视频时长上限（秒）"
    )
    result.add_argument(
        "--max-size-mb", type=positive_int, default=2048, help="视频大小上限（MiB）"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    # Only load this workspace's .env; do not search parent/home directories.
    load_dotenv(Path.cwd() / ".env", override=False)
    args = parser().parse_args(argv)
    # Model downloads stay in the user's selected output root, outside tracked files.
    os.environ.setdefault("HF_HOME", str(args.output.resolve() / "models"))
    try:
        output = run(Options(**vars(args)))
    except PipelineError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已取消；已完成阶段保留，使用相同命令可继续。", file=sys.stderr)
        return 130
    except Exception as exc:
        # Avoid raw exception messages, which can contain provider secrets or private text.
        print(f"处理失败（{type(exc).__name__}），已完成阶段保留。", file=sys.stderr)
        return 1
    print(
        f"\n完成：\n网页：{output / 'note.html'}\nMarkdown：{output / 'note.md'}"
        f"\n导出包：{output / 'note.zip'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
