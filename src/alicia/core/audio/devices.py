"""Choix des périphériques audio (micro, haut-parleur) par nom."""

from __future__ import annotations

import logging

from alicia.core.errors import AliciaError

log = logging.getLogger("alicia.audio")


class AudioError(AliciaError):
    pass


def sounddevice():  # type: ignore[no-untyped-def]
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        raise AudioError(
            "Le module audio (sounddevice) est indisponible.", detail=repr(exc)
        ) from exc
    return sd


def find_device(name: str, *, output: bool) -> int | None:
    """Index du périphérique dont le nom contient ``name`` ; None = périphérique par défaut."""
    if not name:
        return None
    sd = sounddevice()
    key = "max_output_channels" if output else "max_input_channels"
    wanted = name.casefold()
    for index, device in enumerate(sd.query_devices()):
        if device[key] > 0 and wanted in str(device["name"]).casefold():
            return index
    kind = "sortie audio" if output else "micro"
    raise AudioError(
        f"Aucun {kind} ne contient « {name} » dans son nom. "
        "Liste des périphériques : alicia-diag devices",
        detail=f"{kind} introuvable : {name}",
    )


def device_name(index: int | None, *, output: bool) -> str:
    sd = sounddevice()
    try:
        if index is None:
            default = sd.default.device[1 if output else 0]
            index = int(default) if default is not None and int(default) >= 0 else None
        if index is None:
            return "par défaut"
        return str(sd.query_devices(index)["name"])
    except Exception:  # noqa: BLE001 - simple libellé pour les logs
        return f"#{index}"


def list_devices() -> list[str]:
    sd = sounddevice()
    lines = []
    for index, device in enumerate(sd.query_devices()):
        kinds = []
        if device["max_input_channels"] > 0:
            kinds.append("micro")
        if device["max_output_channels"] > 0:
            kinds.append("sortie")
        lines.append(f"{index:>3}  {'/'.join(kinds):<12}  {device['name']}")
    return lines


def device_names(*, output: bool) -> list[str]:
    """Noms des micros (ou sorties) de l'API audio par défaut, sans doublons, pour un menu."""
    sd = sounddevice()
    key = "max_output_channels" if output else "max_input_channels"
    try:
        host = sd.query_hostapis(sd.default.hostapi)
        indexes = list(host["devices"])
    except Exception:  # noqa: BLE001 - API indisponible : tous les périphériques
        indexes = list(range(len(sd.query_devices())))
    names: list[str] = []
    for index in indexes:
        device = sd.query_devices(index)
        name = str(device["name"]).strip()
        if device[key] > 0 and name and name not in names and "mappeur" not in name.lower():
            names.append(name)
    return names
