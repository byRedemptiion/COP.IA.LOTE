"""Préparation du texte pour la synthèse vocale (inspiré de huburton/jarvis, MIT)."""

from __future__ import annotations

import re

_MARKDOWN = [
    (re.compile(r"```.*?```", re.DOTALL), " "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),  # [texte](lien) → texte
    (re.compile(r"https?://\S+"), " "),
    (re.compile(r"(\*\*|__|\*|_|~~)(.+?)\1"), r"\2"),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+", re.MULTILINE), ""),
    (re.compile(r"^\s*>\s?", re.MULTILINE), ""),
    (re.compile(r"[|]"), " "),
]
_SENTENCE_END = re.compile(r"(?<=[.!?…:;])\s+|\n+")


def clean_for_speech(text: str) -> str:
    """Retire le markdown, les liens et les symboles qui se lisent mal à voix haute."""
    for pattern, replacement in _MARKDOWN:
        text = pattern.sub(replacement, text)
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text)  # émojis
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def split_sentences(
    text: str, min_chars: int = 25, max_chars: int = 260, first_max: int = 90
) -> list[str]:
    """Découpe en phrases pour une lecture progressive (la 1re phrase part plus tôt).

    Les phrases très courtes sont regroupées ; les très longues coupées sur une virgule.
    """
    raw = [s.strip() for s in _SENTENCE_END.split(clean_for_speech(text)) if s.strip()]
    sentences: list[str] = []
    for sentence in raw:
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            cut = cut if cut > min_chars else sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            sentences.append(sentence[: cut + 1].strip())
            sentence = sentence[cut + 1 :].strip()
        if sentences and len(sentences[-1]) < min_chars:
            sentences[-1] = f"{sentences[-1]} {sentence}"
        elif sentence:
            sentences.append(sentence)
    sentences = [s for s in sentences if any(c.isalnum() for c in s)]
    # La 1re phrase part plus vite si elle est courte : on la coupe sur une virgule.
    if sentences and len(sentences[0]) > first_max:
        first = sentences[0]
        cut = first.rfind(", ", 12, first_max)
        if cut > 0:
            sentences[0:1] = [first[: cut + 1].strip(), first[cut + 1 :].strip()]
    return sentences
