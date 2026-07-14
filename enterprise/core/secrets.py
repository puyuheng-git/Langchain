"""使用操作系统凭据能力保存系统管理页面中的 API Key。"""

from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path


class _DataBlob(ctypes.Structure):
    """Windows DPAPI 使用的字节缓冲结构。"""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class SecretStore:
    """在 Windows 使用 DPAPI，在其他系统使用系统 Keyring。"""

    def __init__(self, root: Path, service_name: str = "enterprise-ai-workbench") -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        workspace_hash = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()[:16]
        self.service_name = f"{service_name}-{workspace_hash}"

    def get(self, key: str) -> str:
        """读取一个密钥；不存在时返回空字符串。"""

        if os.name == "nt":
            path = self._path(key)
            return self._unprotect(path.read_bytes()).decode("utf-8") if path.is_file() else ""
        keyring = self._keyring()
        return keyring.get_password(self.service_name, key) or ""

    def set(self, key: str, value: str) -> None:
        """保存或清空一个密钥。"""

        if not value:
            self.delete(key)
            return
        if os.name == "nt":
            path = self._path(key)
            path.write_bytes(self._protect(value.encode("utf-8")))
            return
        self._keyring().set_password(self.service_name, key, value)

    def delete(self, key: str) -> None:
        """删除一个已保存密钥。"""

        if os.name == "nt":
            path = self._path(key)
            if path.is_file():
                path.unlink()
            return
        keyring = self._keyring()
        try:
            keyring.delete_password(self.service_name, key)
        except keyring.errors.PasswordDeleteError:
            pass

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.secret"

    @staticmethod
    def _protect(data: bytes) -> bytes:
        input_blob, input_buffer = _blob(data)
        output_blob = _DataBlob()
        result = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "Enterprise AI Workbench",
            None,
            None,
            None,
            0x01,
            ctypes.byref(output_blob),
        )
        del input_buffer
        if not result:
            raise OSError(ctypes.get_last_error(), "DPAPI 加密失败")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _unprotect(data: bytes) -> bytes:
        input_blob, input_buffer = _blob(data)
        output_blob = _DataBlob()
        description = ctypes.c_void_p()
        result = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            0x01,
            ctypes.byref(output_blob),
        )
        del input_buffer
        if not result:
            raise OSError(ctypes.get_last_error(), "DPAPI 解密失败")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("非 Windows 系统保存 API Key 需要安装 keyring") from exc
        return keyring


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    """创建 DPAPI 输入结构并保留底层缓冲区生命周期。"""

    buffer = (ctypes.c_byte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer
