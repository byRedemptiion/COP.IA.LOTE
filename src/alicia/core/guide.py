"""Guides : ouvrir la page utile et montrer son image (carte de quête, emplacement…).

Le robot ne fabrique jamais d'adresse : il ne peut ouvrir que les pages réellement
trouvées par la recherche (les sources de sa réponse). Il le demande par un repère
à la fin de sa réponse ([OUVRIR], [IMAGE]), retiré avant l'affichage et la voix.
"""

from __future__ import annotations

import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from alicia.core.ai.base import Source

log = logging.getLogger("alicia.app")

GUIDE_RULES = """
Pages et images : si le joueur gagnerait à voir la page que tu as trouvée (guide pas à pas,
carte, emplacement d'un PNJ ou d'un objet), écris tout à la fin de ta réponse [OUVRIR] ;
si une image de cette page (carte, emplacement, schéma) l'aiderait, écris [IMAGE].
Mets-les seulement si c'est vraiment utile, et n'écris jamais d'adresse web toi-même."""

_MARKER = re.compile(r"\[(OUVRIR|IMAGE)\]", re.IGNORECASE)
MAX_IMAGE_BYTES = 6_000_000
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) COPIALOTE/1.0"


def take_markers(text: str) -> tuple[str, bool, bool]:
    """(texte sans repères, ouvrir la page ?, montrer l'image ?)."""
    found = {m.upper() for m in _MARKER.findall(text or "")}
    clean = re.sub(r"[ \t]*\n?[ \t]*" + _MARKER.pattern, "", text or "", flags=re.IGNORECASE)
    return clean.rstrip(), "OUVRIR" in found, "IMAGE" in found


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


_OPEN = re.compile(
    r"\b(?:ouvre|ouvrir|affiche|afficher|montre|montrer|lance|mets)\b(?:[- ]?(?:moi|nous))?\s+"
    r"(?:le |la |les |l |un |une |ce |cette )?(?:guide|page|lien|site|source|soluce|tuto)"
)
_IMAGE = re.compile(
    r"\b(?:montre|montrer|affiche|afficher|fais voir)\b(?:[- ]?(?:moi|nous))?\s+"
    r"(?:le |la |les |l |un |une |ce |cette )?(?:carte|image|map|photo|schema|plan|emplacement)"
)

_THING = r"(?:image|carte|photo|fenetre|map|apercu|panneau|plan|schema|capture)"
_CLOSE = re.compile(
    r"\b(?:ferme|fermer|fermes|enleve|enlever|retire|retirer|cache|cacher|vire|virer|supprime|"
    r"masque|masquer|degage|degager)\b(?:[- ]?(?:moi|nous|la|le|l))?\s+"
    r"(?:le |la |les |l |ton |ta |tes |cette |ce |cet )?"
    + _THING
    + r"|\b(?:vois|voit|reste|toujours)\s+(?:encore\s+|toujours\s+)?"
    r"(?:l |la |le |ton |ta |cette |ce )?" + _THING
)


def parse_guide_command(text: str) -> str | None:
    """« ouvre le guide » → "open", « montre-moi la carte » → "image",
    « ferme l'image » → "close", sinon None."""
    plain = re.sub(r"[^\w\s]", " ", _plain(text))
    if len(plain.split()) <= 14 and _CLOSE.search(plain):
        return "close"  # « ferme l'image », « je vois encore l'image que tu m'as montrée »
    plain = re.sub(r"[^\w\s-]", " ", _plain(text))
    if len(plain.split()) > 10:
        return None
    if _IMAGE.search(plain):
        return "image"
    if _OPEN.search(plain):
        return "open"
    return None


def pick_source(sources: list[Source], preferred: tuple[str, ...] = ()) -> Source | None:
    """La meilleure page à ouvrir : d'abord un de tes sites de référence."""
    usable = [s for s in sources if urlparse(s.url).scheme in ("http", "https")]
    if not usable:
        return None
    hosts = [p.split("/")[0].casefold().removeprefix("www.") for p in preferred if p.strip()]
    for source in usable:
        haystack = f"{source.title} {source.url}".casefold()
        if any(host and host in haystack for host in hosts):
            return source
    return usable[0]


@dataclass(frozen=True)
class Preview:
    url: str  # adresse finale de la page (après redirection)
    title: str
    image: bytes
    image_url: str


def _meta_image(page: str) -> str | None:
    for prop in ("og:image", "twitter:image", "og:image:url", "twitter:image:src"):
        for pattern in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{re.escape(prop)}',
        ):
            found = re.search(pattern, page, re.IGNORECASE)
            if found:
                return html.unescape(found.group(1)).strip()
    return None


def fetch_preview(
    url: str, *, timeout_s: float = 8.0, transport: httpx.BaseTransport | None = None
) -> Preview | None:
    """L'image principale d'une page (celle que les sites montrent en aperçu)."""
    try:
        with httpx.Client(
            timeout=timeout_s,
            transport=transport,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
        ) as client:
            page = client.get(url)
            page.raise_for_status()
            text = page.text[:2_000_000]
            final = str(page.url)
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
            image_url = _meta_image(text)
            if not image_url:
                log.info("Guide : pas d'image d'aperçu sur %s", final)
                return None
            image_url = urljoin(final, image_url)
            if urlparse(image_url).scheme not in ("http", "https"):
                return None
            image = client.get(image_url)
            image.raise_for_status()
            if not image.headers.get("content-type", "").startswith("image/"):
                return None
            if len(image.content) > MAX_IMAGE_BYTES:
                return None
    except httpx.HTTPError as exc:
        log.warning("Guide : image introuvable (%r)", exc)
        return None
    return Preview(
        final,
        html.unescape(title.group(1)).strip() if title else final,
        image.content,
        image_url,
    )
