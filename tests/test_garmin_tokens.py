import json

import pytest
from cryptography.fernet import Fernet, InvalidToken

from garmin_tokens import (
    decrypt_tokenstore,
    persist_tokenstore_if_changed,
    remove_plaintext_token,
)


VALID_TOKEN = json.dumps(
    {"di_token": "old-a", "di_refresh_token": "old-r", "di_client_id": "c"}
)


@pytest.fixture
def fernet_key():
    return Fernet.generate_key().decode()


def test_persists_rotated_refresh_token(tmp_path, fernet_key):
    token_path = tmp_path / "plain" / "garmin_tokens.json"
    token_path.parent.mkdir()
    after = json.dumps(
        {"di_token": "new-a", "di_refresh_token": "new-r", "di_client_id": "c"}
    )
    token_path.write_text(after)
    encrypted = tmp_path / "garmin_tokens.enc"

    changed = persist_tokenstore_if_changed(token_path, VALID_TOKEN, encrypted, fernet_key)
    restored = decrypt_tokenstore(encrypted, tmp_path / "restored", fernet_key)

    assert changed is True
    assert json.loads(restored.read_text())["di_refresh_token"] == "new-r"


def test_unchanged_plaintext_does_not_replace_ciphertext(tmp_path, fernet_key):
    token_path = tmp_path / "garmin_tokens.json"
    token_path.write_text(VALID_TOKEN)
    encrypted = tmp_path / "garmin_tokens.enc"
    encrypted.write_bytes(b"existing")

    assert persist_tokenstore_if_changed(token_path, VALID_TOKEN, encrypted, fernet_key) is False
    assert encrypted.read_bytes() == b"existing"


def test_wrong_key_fails_without_plaintext_output(tmp_path, fernet_key):
    encrypted = tmp_path / "garmin_tokens.enc"
    encrypted.write_bytes(Fernet(fernet_key.encode()).encrypt(VALID_TOKEN.encode()))
    output_dir = tmp_path / "plain"

    with pytest.raises(InvalidToken):
        decrypt_tokenstore(encrypted, output_dir, Fernet.generate_key().decode())

    assert not (output_dir / "garmin_tokens.json").exists()


def test_missing_refresh_token_is_rejected(tmp_path, fernet_key):
    token_path = tmp_path / "garmin_tokens.json"
    token_path.write_text(json.dumps({"di_token": "a", "di_client_id": "c"}))

    with pytest.raises(ValueError, match="di_refresh_token"):
        persist_tokenstore_if_changed(
            token_path, VALID_TOKEN, tmp_path / "out.enc", fernet_key
        )


def test_remove_plaintext_is_idempotent(tmp_path):
    token_path = tmp_path / "plain" / "garmin_tokens.json"
    token_path.parent.mkdir()
    token_path.write_text("secret")

    remove_plaintext_token(token_path)
    remove_plaintext_token(token_path)

    assert not token_path.exists()
    assert not token_path.parent.exists()
