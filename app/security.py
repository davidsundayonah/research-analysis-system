"""Small, explicit security boundary for protected research exports.

The key is generated once in the user's application-data directory. The key
file must be protected by the operating system account that owns the app data
directory; the encrypted payload uses Fernet authenticated encryption.
"""

from pathlib import Path
import os
import secrets

from cryptography.fernet import Fernet


class SecureExport:
    SUFFIX = ".raenc"

    def __init__(self, key_path=None):
        self.key_path = Path(key_path) if key_path else self.default_key_path()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_key())

    @staticmethod
    def default_key_path():
        app_data = os.environ.get("APPDATA")
        base = Path(app_data) if app_data else Path.home() / ".local" / "share"
        return base / "ResearchAnalysis" / "export.key"

    def _load_or_create_key(self):
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            Fernet(key)
            return key
        key = Fernet.generate_key()
        temporary = self.key_path.with_name(f".{self.key_path.name}.{secrets.token_hex(8)}.tmp")
        temporary.write_bytes(key)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.key_path)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def encrypt_bytes(self, payload):
        if not isinstance(payload, bytes):
            raise TypeError("Encrypted export payload must be bytes.")
        return self._fernet.encrypt(payload)

    def decrypt_bytes(self, payload):
        if not isinstance(payload, bytes):
            raise TypeError("Encrypted export payload must be bytes.")
        return self._fernet.decrypt(payload)

    def encrypt_file(self, source, destination=None):
        source = Path(source)
        destination = Path(destination) if destination else source.with_suffix(source.suffix + self.SUFFIX)
        destination.write_bytes(self.encrypt_bytes(source.read_bytes()))
        return destination

    def decrypt_file(self, source, destination):
        source, destination = Path(source), Path(destination)
        destination.write_bytes(self.decrypt_bytes(source.read_bytes()))
        return destination
