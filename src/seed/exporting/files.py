"""Exclusive export directories and manifest publication."""

import json
import os
import stat
import sys
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TextIO


class ExportFileError(Exception):
    """A filesystem failure safe to report to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


class ExportDirectory:
    """Track directory and file ownership throughout one export."""

    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._dir_fd: int | None = None
        self._directory = _identity(self.path.lstat())
        self._files: dict[str, tuple[int, int]] = {}
        self._open: set[str] = set()
        self.complete = False
        self._check_directory()
        if sys.platform != "win32":
            self._dir_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _identity(os.fstat(self._dir_fd)) != self._directory:
                self.close()
                raise OSError("Export directory changed.")

    def _check_directory(self) -> None:
        info = self.path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or _identity(info) != self._directory
        ):
            raise OSError("Export directory changed.")

    def _entry(self, name: str) -> str | Path:
        return name if self._dir_fd is not None else self.path / name

    def _check_owned(self, name: str) -> None:
        info = os.lstat(self._entry(name), dir_fd=self._dir_fd)
        if not stat.S_ISREG(info.st_mode) or _identity(info) != self._files[name]:
            raise OSError("Export file changed.")

    def artifact(self, name: str) -> AbstractContextManager[TextIO]:
        """Open one generated basename exclusively."""
        if name in {"manifest.json", "manifest-pending.json"}:
            raise ValueError("Export manifest names are reserved.")
        return self._artifact(name)

    @contextmanager
    def _artifact(self, name: str) -> Iterator[TextIO]:
        if (
            not name
            or name.startswith(".")
            or not all(char in "abcdefghijklmnopqrstuvwxyz0123456789-." for char in name)
            or self.complete
        ):
            raise ValueError("Invalid export artifact name.")
        self._check_directory()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(self._entry(name), flags, 0o600, dir_fd=self._dir_fd)
        try:
            self._files[name] = _identity(os.fstat(fd))
            self._open.add(name)
            stream = os.fdopen(fd, "w", encoding="utf-8", newline="")
        except BaseException:
            os.close(fd)
            raise
        try:
            with stream:
                yield stream
        finally:
            self._open.remove(name)

    def publish(self, manifest: dict[str, object]) -> None:
        """Make the completion marker visible after all artifacts close."""
        if self._open or self.complete or "manifest.json" in self._files:
            raise OSError("Export artifacts are incomplete.")
        for name in self._files:
            self._check_owned(name)
        temporary = "manifest-pending.json"
        with self._artifact(temporary) as stream:
            json.dump(manifest, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        self._check_directory()
        self._check_owned(temporary)
        destination = self._entry("manifest.json")
        try:
            os.lstat(destination, dir_fd=self._dir_fd)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("Export manifest already exists.")
        os.replace(
            self._entry(temporary),
            destination,
            src_dir_fd=self._dir_fd,
            dst_dir_fd=self._dir_fd,
        )
        self.complete = True

    def clean_up(self) -> None:
        """Remove only owned entries and an empty, still-owned directory."""
        if self._dir_fd is None:
            try:
                self._check_directory()
            except OSError:
                return
        for name in self._files:
            try:
                self._check_owned(name)
                os.unlink(self._entry(name), dir_fd=self._dir_fd)
            except OSError:
                continue
        try:
            self._check_directory()
            self.path.rmdir()
        except OSError:
            pass

    def close(self) -> None:
        if self._dir_fd is not None:
            os.close(self._dir_fd)
            self._dir_fd = None


@contextmanager
def export_directory(path: Path) -> Iterator[ExportDirectory]:
    """Create a fresh output directory and clean it up on failure."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise ExportFileError("OUTPUT_EXISTS", "The export destination already exists.") from None
    except OSError:
        raise ExportFileError("EXPORT_FAILED", "Could not create the export directory.") from None
    directory = None
    try:
        directory = ExportDirectory(path)
        yield directory
        if not directory.complete:
            raise OSError("Export did not publish a manifest.")
    except (OSError, UnicodeError):
        raise ExportFileError("EXPORT_FAILED", "Could not finish writing the export.") from None
    finally:
        if directory is not None:
            try:
                if not directory.complete:
                    directory.clean_up()
            finally:
                directory.close()
