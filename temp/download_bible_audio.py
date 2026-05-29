import json
import os
import re
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

JSON_PATH = r"E:\work\bible\bible_audio.json"
OUTPUT_DIR = Path(r"E:\work\bible\音频文件")
FAILED_REPORT = Path(r"E:\work\bible\download_failed.txt")
MAX_WORKERS = 5
TIMEOUT = 30
RETRY_WAIT = 3


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def download_file(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)


def download_with_retry(task: dict) -> dict:
    filename = task["filename"]
    url = task["url"]
    dest = OUTPUT_DIR / filename

    if dest.exists() and dest.stat().st_size > 0:
        return {"status": "skip", "filename": filename}

    for attempt in range(2):
        try:
            download_file(url, dest)
            return {"status": "ok", "filename": filename}
        except Exception as e:
            error = str(e)
            if attempt == 0:
                time.sleep(RETRY_WAIT)

    return {"status": "fail", "filename": filename, "url": url, "error": error}


def build_tasks(data: list) -> list:
    tasks = []
    for entry in data:
        version = sanitize_filename(entry["version"])
        book = sanitize_filename(entry["book"])
        for chapter, url in entry["chapters"].items():
            filename = f"{version}-{book}-{chapter}.mp3"
            tasks.append({"filename": filename, "url": url})
    return tasks


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    tasks = build_tasks(data)
    total = len(tasks)
    print(f"共 {total} 个音频文件待处理，并发线程数：{MAX_WORKERS}\n")

    success = skip = fail = 0
    failures = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(download_with_retry, t): t for t in tasks}
        for future in as_completed(future_map):
            result = future.result()
            done = success + skip + fail + 1
            if result["status"] == "ok":
                success += 1
                print(f"[{done}/{total}] 成功: {result['filename']}")
            elif result["status"] == "skip":
                skip += 1
                print(f"[{done}/{total}] 跳过: {result['filename']}")
            else:
                fail += 1
                failures.append(result)
                print(f"[{done}/{total}] 失败: {result['filename']} -> {result['error']}")

    print(f"\n下载完成。成功: {success}  跳过: {skip}  失败: {fail}  总计: {total}")

    if failures:
        with open(FAILED_REPORT, "w", encoding="utf-8") as f:
            f.write(f"下载失败报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总计: {total}  成功: {success}  跳过: {skip}  失败: {fail}\n")
            f.write("=" * 80 + "\n\n")
            for i, item in enumerate(failures, 1):
                f.write(f"[{i}] 文件名: {item['filename']}\n")
                f.write(f"     URL   : {item['url']}\n")
                f.write(f"     原因  : {item['error']}\n\n")
        print(f"失败详情已写入: {FAILED_REPORT}")
    else:
        print("所有文件下载成功，无失败记录。")


if __name__ == "__main__":
    main()
