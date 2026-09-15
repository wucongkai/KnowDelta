import argparse
from pathlib import Path

from sqlalchemy import select

from knowdelta.storage import read_json

from .config import get_settings
from .db import get_session_factory
from .services import complete_values
from .tables import Job


def import_existing() -> int:
    count = 0
    with get_session_factory()() as db:
        for source in get_settings().jobs_root.glob("*/status.json"):
            status = read_json(source)
            if status.get("status") != "complete" or not status.get("export_path"):
                continue
            directory = Path(status["export_path"]).resolve()
            if not directory.is_relative_to(get_settings().jobs_root) or not directory.is_dir():
                continue
            key = f"import:{source.parent.name}:{directory.name}"
            if db.scalar(select(Job).where(Job.request_key == key)):
                continue
            note = read_json(directory / "note.json")
            values = complete_values(directory)
            db.add(Job(request_key=key, mode=note["mode"], options={}, **values))
            count += 1
        db.commit()
    return count


def main():
    argparse.ArgumentParser(description="将已有 CLI 图文结果导入 Web 笔记库").parse_args()
    print(f"已导入 {import_existing()} 份图文笔记。")
