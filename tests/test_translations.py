"""Translation-file parity checks (UI-02).

These are pure JSON checks (no Home Assistant needed): the German translation
must be valid, must not introduce keys absent from the English source strings,
and must cover exactly the same config/selector keys as the English translation.
"""

from __future__ import annotations

import json
from pathlib import Path

_COMPONENT = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "value_crossing"
)
_STRINGS = _COMPONENT / "strings.json"
_EN = _COMPONENT / "translations" / "en.json"
_DE = _COMPONENT / "translations" / "de.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key_paths(obj, prefix: str = "") -> set[str]:
    """All dotted key paths in a nested dict (leaf values ignored)."""
    paths: set[str] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths |= _key_paths(value, path)
    return paths


def test_de_is_valid_json() -> None:
    assert isinstance(_load(_DE), dict)


def test_de_keys_are_subset_of_strings() -> None:
    # Home Assistant rejects translation keys that are absent from strings.json.
    de_keys = _key_paths(_load(_DE))
    strings_keys = _key_paths(_load(_STRINGS))
    assert de_keys <= strings_keys, de_keys - strings_keys


def test_de_covers_same_config_and_selector_as_en() -> None:
    # Every translatable config-flow / selector string in English is also in
    # German (and no extra ones), so nothing renders untranslated.
    en, de = _load(_EN), _load(_DE)
    sections = ("config", "selector")
    en_keys = _key_paths({s: en[s] for s in sections})
    de_keys = _key_paths({s: de[s] for s in sections})
    assert de_keys == en_keys, en_keys ^ de_keys


def test_de_omits_entity_names_for_english_fallback() -> None:
    # Entity display names are intentionally left English (UI-02 decision).
    assert "entity" not in _load(_DE)


def test_de_has_no_em_or_en_dashes() -> None:
    text = _DE.read_text(encoding="utf-8")
    assert "—" not in text  # em dash
    assert "–" not in text  # en dash
