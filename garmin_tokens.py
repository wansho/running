#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet


TOKEN_FIELDS = ("di_token", "di_refresh_token", "di_client_id")


def validate_token_json(content: str) -> dict[str, str]:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("tokenstore 必须是 JSON 对象")
    for field in TOKEN_FIELDS:
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"tokenstore 缺少有效字段：{field}")
    return {field: data[field] for field in TOKEN_FIELDS}


def _write_bytes_atomic(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        temporary_path = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(mode)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def encrypt_tokenstore(token_path: Path, encrypted_path: Path, key: str) -> None:
    content = Path(token_path).read_text(encoding="utf-8")
    validate_token_json(content)
    ciphertext = Fernet(key.encode()).encrypt(content.encode())
    _write_bytes_atomic(Path(encrypted_path), ciphertext)


def decrypt_tokenstore(encrypted_path: Path, output_dir: Path, key: str) -> Path:
    ciphertext = Path(encrypted_path).read_bytes()
    plaintext = Fernet(key.encode()).decrypt(ciphertext).decode()
    validate_token_json(plaintext)
    output_path = Path(output_dir) / "garmin_tokens.json"
    _write_bytes_atomic(output_path, plaintext.encode())
    return output_path


def persist_tokenstore_if_changed(
    token_path: Path,
    original_json: str,
    encrypted_path: Path,
    key: str,
) -> bool:
    current = Path(token_path).read_text(encoding="utf-8")
    current_data = validate_token_json(current)
    original_data = validate_token_json(original_json)
    if current_data == original_data:
        return False
    ciphertext = Fernet(key.encode()).encrypt(current.encode())
    _write_bytes_atomic(Path(encrypted_path), ciphertext)
    return True


def remove_plaintext_token(path: Path) -> None:
    path = Path(path)
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except (FileNotFoundError, OSError):
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="加密或解密 Garmin tokenstore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    encrypt_parser = subparsers.add_parser("encrypt")
    encrypt_parser.add_argument("--input", type=Path, required=True)
    encrypt_parser.add_argument("--output", type=Path, required=True)
    decrypt_parser = subparsers.add_parser("decrypt")
    decrypt_parser.add_argument("--input", type=Path, required=True)
    decrypt_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    key = os.environ.get("GARMIN_TOKEN_KEY")
    if not key:
        parser.error("环境变量 GARMIN_TOKEN_KEY 未设置")
    if args.command == "encrypt":
        encrypt_tokenstore(args.input, args.output, key)
    else:
        decrypt_tokenstore(args.input, args.output_dir, key)


if __name__ == "__main__":
    main()
