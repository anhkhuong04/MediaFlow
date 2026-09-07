"""The narrow, framework-neutral subset of the core facade used by presentation."""

from collections.abc import Callable
from typing import Protocol

from mediaflow.application import (
    AnalysisRequest,
    ApplicationEvent,
    CommandResult,
    DependencyStatusView,
    DownloadItemView,
    DownloadsView,
    HistoryItemView,
    HistoryRemovalView,
    SettingsView,
    TaskDetailsView,
)
from mediaflow.application.ports import EventSubscription


class PresentationFacade(Protocol):
    """Typed C8 contract consumed by controllers; widgets never receive this object."""

    def subscribe(self, subscriber: Callable[[ApplicationEvent], None]) -> EventSubscription: ...

    def analyze(self, source_url: str) -> AnalysisRequest: ...

    def cancel_analysis(self, request_id: str) -> bool: ...

    def enqueue(
        self, *, configuration_id: str, preset_id_value: str, output_directory: str
    ) -> CommandResult[DownloadItemView]: ...

    def cancel(self, task_id: str) -> CommandResult[DownloadItemView]: ...

    def retry(self, task_id: str) -> CommandResult[DownloadItemView]: ...

    def resume(self, task_id: str) -> CommandResult[DownloadItemView]: ...

    def restart(self, task_id: str) -> CommandResult[DownloadItemView]: ...

    def retry_processing(self, task_id: str) -> CommandResult[DownloadItemView]: ...

    def downloads(self) -> DownloadsView: ...

    def history(self) -> tuple[HistoryItemView, ...]: ...

    def remove_history(
        self, task_id: str, *, delete_output: bool
    ) -> CommandResult[HistoryRemovalView]: ...

    def task_details(self, task_id: str) -> CommandResult[TaskDetailsView]: ...

    def load_settings(self) -> SettingsView: ...

    def dependency_status(self) -> tuple[DependencyStatusView, ...]: ...

    def acknowledge_startup_check(self) -> CommandResult[SettingsView]: ...

    def save_settings(
        self,
        *,
        default_output_directory: str,
        default_preset_id: str,
        concurrent_downloads: int,
        default_audio_preset_id: str,
        theme: str,
        language: str,
    ) -> CommandResult[SettingsView]: ...
