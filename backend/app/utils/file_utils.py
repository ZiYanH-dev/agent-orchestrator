"""文件处理工具函数。"""
from __future__ import annotations

import uuid
from pathlib import Path

from app.config.settings import settings


def save_upload_file(file_bytes: bytes, original_filename: str) -> Path:
    """保存上传文件到数据目录。

    Args:
        file_bytes: 文件二进制内容。
        original_filename: 原始文件名。

    Returns:
        Path: 保存后的文件绝对路径。
    """
    data_dir: Path = settings.data_dir_path
    data_dir.mkdir(parents=True, exist_ok=True)

    suffix: str = Path(original_filename).suffix
    unique_name: str = f"{uuid.uuid4().hex}{suffix}"
    target_path: Path = data_dir / unique_name
    target_path.write_bytes(file_bytes)
    return target_path
