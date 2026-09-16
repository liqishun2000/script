"""Fetch the pinned official scrcpy Windows runtime for development/packaging."""
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


VERSION = "4.1"
URL = f"https://github.com/Genymobile/scrcpy/releases/download/v{VERSION}/scrcpy-win64-v{VERSION}.zip"
SHA256 = "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"


def main():
    destination = Path(__file__).resolve().parent / "runtime" / "scrcpy"
    if destination.exists():
        raise SystemExit(f"Already present: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as folder:
        folder = Path(folder)
        archive = folder / "scrcpy.zip"
        with urllib.request.urlopen(URL, timeout=60) as source, archive.open("wb") as target:
            shutil.copyfileobj(source, target)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != SHA256:
            raise RuntimeError("scrcpy SHA-256 mismatch")
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if not (folder / entry.filename).resolve().is_relative_to(folder.resolve()):
                    raise RuntimeError("Invalid archive path")
            package.extractall(folder)
        (folder / f"scrcpy-win64-v{VERSION}").rename(destination)
    print(f"Verified scrcpy {VERSION}: {destination}")


if __name__ == "__main__":
    main()
