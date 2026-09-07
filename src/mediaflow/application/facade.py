"""Small UI-facing facade over application commands, queries, and read models."""

import logging
from collections.abc import Callable
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import uuid4

from mediaflow.application.download_manager import CancellationSignal
from mediaflow.application.events import ApplicationEvent
from mediaflow.application.messages import (
    SuggestedAction,
    UserMessage,
    command_message,
    message_for_failure,
)
from mediaflow.application.models import ApplicationSettings, ResumeMode
from mediaflow.application.ports import (
    DependencyProbe,
    EventSource,
    EventSubscription,
    OutputFileInspector,
    RecoveryStore,
    SettingsStore,
    TaskRepository,
    TaskScheduler,
)
from mediaflow.application.recovery import (
    PrepareProcessingRetry,
    PrepareResume,
    RestartDownload,
    ResumeUnavailable,
)
from mediaflow.application.use_cases import (
    AnalyzeUrl,
    CancelDownload,
    EnqueueDownload,
    RetryDownload,
)
from mediaflow.application.view_models import (
    DependencyStatusView,
    DownloadItemView,
    DownloadsView,
    HistoryItemView,
    MediaConfigurationView,
    SettingsView,
    TaskDetailsView,
    dependency_views,
    downloads_view,
    history_view,
    media_view,
    preset_id,
    task_details_view,
    task_item_view,
)
from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    DownloadPreset,
    MediaInfo,
    OutputPath,
    SourceUrl,
    TaskId,
    TaskState,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)

_LOGGER = logging.getLogger("mediaflow.facade")


@dataclass(frozen=True, slots=True)
class CommandResult[T]:
    value: T | None = None
    error: UserMessage | None = None

    def __post_init__(self) -> None:
        if (self.value is None) == (self.error is None):
            raise ValueError("Command result must contain exactly one outcome")

    @classmethod
    def succeeded(cls, value: T) -> "CommandResult[T]":
        return cls(value=value)

    @classmethod
    def failed(cls, error: UserMessage) -> "CommandResult[T]":
        return cls(error=error)


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    request_id: str
    result: Future[CommandResult[MediaConfigurationView]]


class ApplicationFacade:
    """Framework-free API intended to be wrapped by a Qt presentation bridge."""

    def __init__(
        self,
        *,
        analyze_url: AnalyzeUrl,
        enqueue_download: EnqueueDownload,
        cancel_download: CancelDownload,
        retry_download: RetryDownload,
        prepare_resume: PrepareResume,
        restart_download: RestartDownload,
        prepare_processing_retry: PrepareProcessingRetry,
        repository: TaskRepository,
        settings: SettingsStore,
        dependencies: DependencyProbe,
        recovery_store: RecoveryStore,
        output_files: OutputFileInspector,
        events: EventSource,
        queue: TaskScheduler,
        analysis_executor: Executor,
    ) -> None:
        self._analyze_url = analyze_url
        self._enqueue_download = enqueue_download
        self._cancel_download = cancel_download
        self._retry_download = retry_download
        self._prepare_resume = prepare_resume
        self._restart_download = restart_download
        self._prepare_processing_retry = prepare_processing_retry
        self._repository = repository
        self._settings = settings
        self._dependencies = dependencies
        self._recovery_store = recovery_store
        self._output_files = output_files
        self._events = events
        self._queue = queue
        self._analysis_executor = analysis_executor
        self._lock = RLock()
        self._analysis_signals: dict[str, CancellationSignal] = {}
        self._media: dict[str, MediaInfo] = {}
        self._presets: dict[str, dict[str, DownloadPreset]] = {}

    def subscribe(self, subscriber: Callable[[ApplicationEvent], None]) -> EventSubscription:
        return self._events.subscribe(subscriber)

    def analyze(self, source_url: str) -> AnalysisRequest:
        request_id = str(uuid4())
        try:
            normalized_url = SourceUrl(source_url)
        except ValueError:
            future: Future[CommandResult[MediaConfigurationView]] = Future()
            future.set_result(CommandResult.failed(command_message("error.invalid_url")))
            return AnalysisRequest(request_id, future)

        signal = CancellationSignal()
        with self._lock:
            self._analysis_signals[request_id] = signal
        result = self._analysis_executor.submit(
            self._run_analysis, request_id, normalized_url, signal
        )
        result.add_done_callback(lambda _: self._forget_analysis_signal(request_id))
        return AnalysisRequest(request_id, result)

    def cancel_analysis(self, request_id: str) -> bool:
        with self._lock:
            signal = self._analysis_signals.get(request_id)
            if signal is None:
                return False
            signal.cancel()
            return True

    def cancel_all_analyses(self) -> None:
        with self._lock:
            signals = tuple(self._analysis_signals.values())
        for signal in signals:
            signal.cancel()

    def enqueue(
        self,
        *,
        configuration_id: str,
        preset_id_value: str,
        output_directory: str,
    ) -> CommandResult[DownloadItemView]:
        with self._lock:
            media = self._media.get(configuration_id)
            preset = self._presets.get(configuration_id, {}).get(preset_id_value)
        if media is None:
            return CommandResult.failed(command_message("error.analysis_expired"))
        if preset is None:
            return CommandResult.failed(command_message("error.preset_invalid"))
        try:
            output = OutputPath(Path(output_directory))
            task = self._enqueue_download.execute(
                media=media, preset=preset, output_directory=output
            )
            self._queue.enqueue(task.task_id)
            return CommandResult.succeeded(self._task_item(task.task_id))
        except (ValueError, OSError):
            return CommandResult.failed(
                command_message("error.enqueue", action=SuggestedAction.CHOOSE_FOLDER)
            )
        except RuntimeError:
            return CommandResult.failed(command_message("error.queue_unavailable"))

    def cancel(self, task_id: str) -> CommandResult[DownloadItemView]:
        parsed = self._parse_task_id(task_id)
        if parsed is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        task = self._repository.get(parsed)
        if task is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        try:
            if task.state in {TaskState.PAUSED, TaskState.INTERRUPTED}:
                self._cancel_download.execute(parsed)
            elif not self._queue.cancel(parsed):
                return CommandResult.failed(command_message("error.action_unavailable"))
            return CommandResult.succeeded(self._task_item(parsed))
        except (RuntimeError, ValueError):
            return CommandResult.failed(command_message("error.action_unavailable"))

    def retry(self, task_id: str) -> CommandResult[DownloadItemView]:
        parsed = self._parse_task_id(task_id)
        if parsed is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        try:
            task = self._retry_download.execute(parsed)
            self._queue.enqueue(task.task_id)
            return CommandResult.succeeded(self._task_item(parsed))
        except (LookupError, RuntimeError, ValueError):
            return CommandResult.failed(command_message("error.action_unavailable"))

    def resume(self, task_id: str) -> CommandResult[DownloadItemView]:
        parsed = self._parse_task_id(task_id)
        if parsed is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        try:
            plan = self._prepare_resume.execute(parsed)
            if plan.mode is ResumeMode.DOWNLOAD:
                self._queue.enqueue(parsed)
            elif plan.artifact is not None:
                self._queue.enqueue_processing(parsed, plan.artifact)
            return CommandResult.succeeded(self._task_item(parsed))
        except ResumeUnavailable as error:
            return CommandResult.failed(
                command_message(error.code, action=SuggestedAction.VIEW_DETAILS)
            )
        except (LookupError, RuntimeError, ValueError):
            return CommandResult.failed(command_message("error.action_unavailable"))

    def restart(self, task_id: str) -> CommandResult[DownloadItemView]:
        parsed = self._parse_task_id(task_id)
        if parsed is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        try:
            plan = self._restart_download.execute(parsed)
            self._queue.enqueue(plan.task.task_id)
            return CommandResult.succeeded(self._task_item(parsed))
        except (LookupError, RuntimeError, ValueError):
            return CommandResult.failed(command_message("error.action_unavailable"))

    def retry_processing(self, task_id: str) -> CommandResult[DownloadItemView]:
        parsed = self._parse_task_id(task_id)
        if parsed is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        try:
            plan = self._prepare_processing_retry.execute(parsed)
            if plan.artifact is None:
                raise AssertionError("Processing retry plan requires an artifact")
            self._queue.enqueue_processing(parsed, plan.artifact)
            return CommandResult.succeeded(self._task_item(parsed))
        except ResumeUnavailable as error:
            return CommandResult.failed(
                command_message(error.code, action=SuggestedAction.VIEW_DETAILS)
            )
        except (LookupError, RuntimeError, ValueError):
            return CommandResult.failed(command_message("error.action_unavailable"))

    def downloads(self) -> DownloadsView:
        return downloads_view(
            self._repository.list_downloads(),
            recovery_store=self._recovery_store,
            output_files=self._output_files,
        )

    def history(self) -> tuple[HistoryItemView, ...]:
        return history_view(
            self._repository.list_history(),
            recovery_store=self._recovery_store,
            output_files=self._output_files,
        )

    def task_details(self, task_id: str) -> CommandResult[TaskDetailsView]:
        parsed = self._parse_task_id(task_id)
        task = self._repository.get(parsed) if parsed is not None else None
        if task is None:
            return CommandResult.failed(command_message("error.task_not_found"))
        return CommandResult.succeeded(
            task_details_view(
                task,
                recovery_store=self._recovery_store,
                output_files=self._output_files,
            )
        )

    def load_settings(self) -> SettingsView:
        settings = self._settings.load()
        return SettingsView(
            default_output_directory=str(settings.default_output_directory),
            default_preset_id=preset_id(settings.default_preset),
            concurrent_downloads=settings.concurrent_downloads,
        )

    def save_settings(
        self,
        *,
        default_output_directory: str,
        default_preset_id: str,
        concurrent_downloads: int,
    ) -> CommandResult[SettingsView]:
        preset = _known_presets().get(default_preset_id)
        if preset is None:
            return CommandResult.failed(command_message("error.preset_invalid"))
        try:
            settings = ApplicationSettings(
                OutputPath(Path(default_output_directory)),
                preset,
                concurrent_downloads,
            )
            self._settings.save(settings)
            return CommandResult.succeeded(self.load_settings())
        except (OSError, ValueError):
            return CommandResult.failed(command_message("error.settings_invalid"))

    def dependency_status(self) -> tuple[DependencyStatusView, ...]:
        return dependency_views(self._dependencies.probe())

    def _run_analysis(
        self,
        request_id: str,
        source_url: SourceUrl,
        signal: CancellationSignal,
    ) -> CommandResult[MediaConfigurationView]:
        try:
            operation = self._analyze_url.execute(source_url, cancellation=signal)
        except Exception:
            _LOGGER.warning("application.failed")
            return CommandResult.failed(command_message("error.unexpected"))
        if operation.result is not None:
            presets = _known_presets()
            with self._lock:
                self._media[request_id] = operation.result
                self._presets[request_id] = presets
            return CommandResult.succeeded(media_view(request_id, operation.result))
        if operation.failure is not None:
            return CommandResult.failed(message_for_failure(operation.failure))
        return CommandResult.failed(command_message("status.cancelled"))

    def _forget_analysis_signal(self, request_id: str) -> None:
        with self._lock:
            self._analysis_signals.pop(request_id, None)

    def _task_item(self, task_id: TaskId) -> DownloadItemView:
        task = self._repository.get(task_id)
        if task is None:
            raise LookupError(str(task_id))
        return task_item_view(
            task,
            recovery_store=self._recovery_store,
            output_files=self._output_files,
        )

    @staticmethod
    def _parse_task_id(value: str) -> TaskId | None:
        try:
            return TaskId.parse(value)
        except (TypeError, ValueError):
            return None


def _known_presets() -> dict[str, DownloadPreset]:
    presets: tuple[DownloadPreset, ...] = (
        *(
            VideoPreset(quality, container)
            for quality in VideoQuality
            for container in VideoContainer
        ),
        *(AudioPreset(container=container) for container in AudioContainer),
    )
    return {preset_id(preset): preset for preset in presets}
