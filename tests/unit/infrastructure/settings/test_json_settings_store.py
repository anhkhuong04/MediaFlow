from pathlib import Path

from mediaflow.application import (
    ApplicationSettings,
    LanguagePreference,
    ThemePreference,
)
from mediaflow.domain import AudioContainer, AudioPreset, OutputPath, VideoPreset
from mediaflow.infrastructure.settings import JsonSettingsStore


def test_json_settings_round_trip_and_invalid_document_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    defaults = ApplicationSettings(OutputPath(tmp_path.resolve()), VideoPreset(), 2)
    store = JsonSettingsStore(path, defaults)
    assert store.load() == defaults

    changed = ApplicationSettings(
        OutputPath((tmp_path / "downloads").resolve()),
        AudioPreset(container=AudioContainer.MP3),
        4,
        AudioPreset(container=AudioContainer.M4A),
        ThemePreference.DARK,
        LanguagePreference.VIETNAMESE,
        True,
    )
    store.save(changed)
    assert store.load() == changed
    assert not path.with_name(".settings.json.tmp").exists()

    path.write_text("not json", encoding="utf-8")
    assert store.load() == defaults
