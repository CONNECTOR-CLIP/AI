from __future__ import annotations

import os
import sys
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
SUBMODULE_DIR = ROOT / "external" / "idea_novelty_checker"


def ensure_submodule_importable() -> None:
    """external/idea_novelty_checker를 `noveltychecker` 패키지로 import할 수 있게 sys.path에 추가한다.
    pip 설치용 패키지가 아니라 clone-and-run 구조라 경로를 직접 등록해야 한다."""
    path = str(SUBMODULE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)


@contextmanager
def submodule_cwd():
    """idea_novelty_checker 내부 코드는 incontext_examples 파일을 상대경로로 연다
    (예: check_novelty.py가 "noveltychecker/models/.../relaxed.json"을 그대로 open한다).
    따라서 그 파일들을 실제로 읽는 호출(get_review 등) 동안만 작업 디렉터리를 서브모듈로 옮긴다."""
    previous = Path.cwd()
    os.chdir(SUBMODULE_DIR)
    try:
        yield
    finally:
        os.chdir(previous)


def load_config(config_path: str | Path | None = None) -> None:
    ensure_submodule_importable()
    from noveltychecker.utils.load_env import load_env

    path = Path(config_path) if config_path else ROOT / "config.yml"
    load_env(config_path=str(path))
