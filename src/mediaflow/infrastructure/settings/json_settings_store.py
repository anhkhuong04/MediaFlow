"""Small atomic JSON settings store for framework-independent preferences."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mediaflow.application import ApplicationSettings, LanguagePreference, ThemePreference
from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    AudioQuality,
    OutputPath,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)


@dataclass(frozen=True, slots=True)
class JsonSettingsStore:
    path: Path
    defaults: ApplicationSettings

    def load(self) -> ApplicationSettings:
        if not self.path.exists():
            return self.defaults
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Settings document must be an object")
            raw_preset = raw.get("default_preset")
            if not isinstance(raw_preset, dict):
                raise ValueError("Default preset must be an object")
            preset = _deserialize_preset(cast(dict[str, object], raw_preset))
            output = raw.get("default_output_directory")
            concurrency = raw.get("concurrent_downloads")
            if (
                not isinstance(output, str)
                or isinstance(concurrency, bool)
                or not isinstance(concurrency, int)
            ):
                raise ValueError("Settings values have invalid types")
            audio_preset = _deserialize_audio_preset(raw.get("default_audio_preset"))
            theme = ThemePreference(raw.get("theme", self.defaults.theme.value))
            language = LanguagePreference(raw.get("language", self.defaults.language.value))
            startup_check_seen = raw.get("startup_check_seen", self.defaults.startup_check_seen)
            if not isinstance(startup_check_seen, bool):
                raise ValueError("Startup check setting has an invalid type")
            return ApplicationSettings(
                OutputPath(Path(output)),
                preset,
                concurrency,
                audio_preset,
                theme,
                language,
                startup_check_seen,
            )
        except (AttributeError, OSError, TypeError, ValueError, json.JSONDecodeError):
            # Invalid local preferences are not allowed to prevent application
            # startup. Defaults remain authoritative until the next explicit save.
            return self.defaults

    def save(self, settings: ApplicationSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = {
            "version": 2,
            "default_output_directory": str(settings.default_output_directory),
            "default_preset": _serialize_preset(settings.default_preset),
            "concurrent_downloads": settings.concurrent_downloads,
            "default_audio_preset": _serialize_preset(settings.default_audio_preset),
            "theme": settings.theme.value,
            "language": settings.language.value,
            "startup_check_seen": settings.startup_check_seen,
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def _serialize_preset(preset: VideoPreset | AudioPreset) -> dict[str, object]:
    if isinstance(preset, VideoPreset):
        return {
            "kind": "video",
            "quality": preset.quality.value,
            "container": preset.container.value,
            "frames_per_second": preset.preferred_frames_per_second,
        }
    return {
        "kind": "audio",
        "quality": preset.quality.value,
        "container": preset.container.value,
    }


def _deserialize_preset(raw: dict[str, object]) -> VideoPreset | AudioPreset:
    kind = raw.get("kind")
    quality = raw.get("quality")
    container = raw.get("container")
    if not all(isinstance(value, str) for value in (kind, quality, container)):
        raise ValueError("Preset values have invalid types")
    if kind == "video":
        fps = raw.get("frames_per_second")
        if fps is not None and (isinstance(fps, bool) or not isinstance(fps, int)):
            raise ValueError("Video frame rate has an invalid type")
        return VideoPreset(
            VideoQuality(cast(str, quality)),
            VideoContainer(cast(str, container)),
            fps,
        )
    if kind == "audio":
        return AudioPreset(
            AudioQuality(cast(str, quality)),
            AudioContainer(cast(str, container)),
        )
    raise ValueError("Unknown preset kind")


def _deserialize_audio_preset(raw: object) -> AudioPreset:
    if raw is None:
        return AudioPreset()
    preset = _deserialize_preset(cast(dict[str, object], raw))
    if not isinstance(preset, AudioPreset):
        raise ValueError("Default audio preset must be an audio preset")
    return preset
