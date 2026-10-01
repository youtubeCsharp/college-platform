# -*- coding: utf-8 -*-
"""每日备份:data/ 与 files/ 全量复制到 backups/日期时间/,保留最近 90 天。

配合 Windows 计划任务每日自动执行(命令见 README),也可双击 每日备份.bat 手动备份。
"""
import shutil
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KEEP_DAYS = 90

def main():
    ts = time.strftime("%Y-%m-%d_%H%M")
    dest = BASE / "backups" / ts
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("data", "files"):
        src = BASE / name
        if src.exists():
            shutil.copytree(src, dest / name, dirs_exist_ok=True)
    print(f"备份完成: {dest}")
    now = time.time()
    for p in (BASE / "backups").iterdir():
        if p.is_dir():
            try:
                if now - p.stat().st_mtime > KEEP_DAYS * 86400:
                    shutil.rmtree(p)
                    print(f"清理过期备份: {p.name}")
            except OSError:
                pass

if __name__ == "__main__":
    main()
