"""Coordinate portable session export without owning CLI or RPC presentation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pico.runtime.sessions.export import default_export_path, verify_export, write_portable_export
from pico.runtime.sessions.service import SessionManager


@dataclass(frozen=True)
class SessionExportResult:
    status: Literal["exported", "not_found", "ambiguous", "write_failed", "verification_failed"]
    path: Path | None = None
    destination: Path | None = None
    candidates: tuple[str, ...] = ()
    error: OSError | None = None


def export_session(manager: SessionManager, value: str, *, output: Path | None = None) -> SessionExportResult:
    """Resolve, write and verify an existing session, never creating one on lookup.

    The caller owns manager lifetime and output presentation. Export reads stored
    conversation state and does not replay tools or require an idle execution lane.
    """
    resolution = manager.resolve_key(value)
    if resolution.status == "ambiguous":
        return SessionExportResult("ambiguous", candidates=tuple(resolution.candidates))
    session = manager.peek(resolution.key) if resolution.status == "resolved" else None
    if session is None:
        return SessionExportResult("not_found")
    destination = output if output is not None else default_export_path(manager.workspace, resolution.key)
    try:
        written = write_portable_export(session, destination)
    except OSError as exc:
        return SessionExportResult("write_failed", destination=destination, error=exc)
    status = "exported" if verify_export(written) else "verification_failed"
    return SessionExportResult(status, path=written, destination=destination)
