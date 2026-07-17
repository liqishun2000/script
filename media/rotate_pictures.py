"""图片顺时针旋转脚本。

修改顶部 IMAGE_PATH / ROTATION_DEGREES 后直接运行::

    python rotate_pictures.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

IMAGE_PATH = r"E:\tem\anv_ti_perm_detail_collapse.webp"  # 单文件或目录
ROTATION_DEGREES = 90  # 顺时针角度

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def collect_files(source: Path) -> tuple[list[Path], Path]:
    if source.is_dir():
        files = sorted(
            p
            for p in source.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )
        output_dir = source.parent / f"{source.name}-output"
        return files, output_dir

    if source.is_file():
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise SystemExit(f"不是支持的图片格式: {source.name}")
        output_dir = source.parent / f"{source.stem}-output"
        return [source], output_dir

    raise SystemExit(f"不是有效文件或目录: {source}")


def rotate_clockwise(img: Image.Image, degrees: int) -> Image.Image:
    # Pillow 正角为逆时针，取负实现顺时针；expand=True 保证不裁切
    return img.rotate(-degrees, expand=True)


def main() -> None:
    source = Path(IMAGE_PATH)
    if not source.exists():
        raise SystemExit(f"路径不存在: {source}")

    files, output_dir = collect_files(source)
    if not files:
        print(f"未找到图片文件: {source}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    for file in files:
        try:
            with Image.open(file) as img:
                rotated = rotate_clockwise(img, ROTATION_DEGREES)
                out_file = output_dir / file.name
                # 保留原格式；JPEG 等无 alpha 的格式由 Pillow 按模式处理
                save_kwargs = {}
                if file.suffix.lower() in {".jpg", ".jpeg"} and rotated.mode in {
                    "RGBA",
                    "P",
                }:
                    rotated = rotated.convert("RGB")
                rotated.save(out_file, **save_kwargs)
            print(f"已输出: {out_file}")
        except Exception as e:
            print(f"跳过（处理失败）: {file.name} — {e}")


if __name__ == "__main__":
    main()
