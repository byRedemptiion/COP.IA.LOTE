"""Logs horodatés : fichier tournant, console et panneau de l'interface.

Chaque opération (capture, analyse) peut porter un identifiant court via ``operation_id``,
ajouté automatiquement à chaque ligne : ``[a3f9c2]``.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import logging.handlers
import sys
import threading
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

_operation: contextvars.ContextVar[str] = contextvars.ContextVar("alicia_operation", default="-")

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-18s [%(op)s] %(message)s"


class _Formatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: N802
        moment = datetime.fromtimestamp(record.created).astimezone()
        return moment.isoformat(timespec="milliseconds")


class _OperationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.op = _operation.get()
        return True


def new_operation_id() -> str:
    return uuid.uuid4().hex[:6]


@contextlib.contextmanager
def operation(op_id: str | None = None) -> Iterator[str]:
    """Associe un identifiant aux logs émis dans ce bloc (même thread)."""
    op_id = op_id or new_operation_id()
    token = _operation.set(op_id)
    try:
        yield op_id
    finally:
        _operation.reset(token)


def make_formatter() -> logging.Formatter:
    return _Formatter(LOG_FORMAT)


def make_filter() -> logging.Filter:
    return _OperationFilter()


def setup_logging(log_dir: Path, level: str = "INFO", *, console: bool = True) -> Path:
    """Configure le logger racine ``alicia`` et renvoie le chemin du fichier de log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "alicia.log"
    root = logging.getLogger("alicia")
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = make_formatter()
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    handlers: list[logging.Handler] = [file_handler]
    if console and sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(_OperationFilter())
        root.addHandler(handler)
    _install_exception_hooks()
    return log_file


def set_level(level: str) -> None:
    logging.getLogger("alicia").setLevel(level)


def _install_exception_hooks() -> None:
    log = logging.getLogger("alicia.crash")

    def excepthook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Exception non gérée", exc_info=(exc_type, exc, tb))

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        log.critical(
            "Exception non gérée dans le thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),  # type: ignore[arg-type]
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
