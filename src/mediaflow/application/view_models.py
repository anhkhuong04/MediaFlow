"""Framework-neutral read models consumed by the future presentation layer."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from mediaflow.application.messages import UserMessage, message_for_failure
from mediaflow.application.models import DependencyReport, DependencyState
from mediaflow.application.ports import OutputFileInspector, RecoveryStore
from mediaflow.domain import (
    AudioContainer,
    AudioPreset,
    DownloadPreset,
    DownloadTask,
    MediaInfo,
    TaskState,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)


class MediaKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"


class DownloadStatus(StrEnum):
    WAITING = "waiting"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PresetOptionView:
    preset_id: str
    kind: MediaKind
    quality: str
    container: str
    frames_per_second: int | None
    available: bool
    unavailable_reason_key: str | None = None
    requires_processing: bool = False


@dataclass(frozen=True, slots=True)
class MediaConfigurationView:
    configuration_id: str
    source_url: str
    title: str
    source_name: str
    uploader: str | None
    duration_seconds: float | None
    thumbnail_url: str | None
    is_live: bool
    playlist_item_count: int | None
    presets: tuple[PresetOptionView, ...]


@dataclass(frozen=True, slots=True)
class ProgressView:
    stage: str
    fraction: float | None
    downloaded_bytes: int | None
    total_bytes: int | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None


@dataclass(frozen=True, slots=True)
class TaskActionsView:
    can_cancel: bool
    can_retry: bool
    can_resume: bool
    can_restart: bool
    can_retry_processing: bool
    can_open_output: bool


@dataclass(frozen=True, slots=True)
class DownloadItemView:
    task_id: str
    attempt_id: str
    title: str
    preset_kind: MediaKind
    quality: str
    container: str
    status: DownloadStatus
    created_at: datetime
    updated_at: datetime
    progress: ProgressView | None
    failure: UserMessage | None
    output_path: str | None
    actions: TaskActionsView


@dataclass(frozen=True, slots=True)
class DownloadSummaryView:
    active: int
    queued: int
    completed: int
    failed: int


@dataclass(frozen=True, slots=True)
class DownloadsView:
    summary: DownloadSummaryView
    items: tuple[DownloadItemView, ...]


@dataclass(frozen=True, slots=True)
class AttemptView:
    attempt_id: str
    number: int
    status: DownloadStatus
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    failure: UserMessage | None


@dataclass(frozen=True, slots=True)
class TaskDetailsView:
    item: DownloadItemView
    source_url: str
    output_directory: str
    attempts: tuple[AttemptView, ...]


@dataclass(frozen=True, slots=True)
class HistoryItemView:
    task_id: str
    title: str
    status: DownloadStatus
    preset_kind: MediaKind
    quality: str
    container: str
    finished_at: datetime
    output_path: str | None
    failure: UserMessage | None
    actions: TaskActionsView


@dataclass(frozen=True, slots=True)
class HistoryRemovalView:
    """Result of an explicit history-removal command, without exposing a path."""

    task_id: str
    output_delete_requested: bool
    output_deleted: bool


@dataclass(frozen=True, slots=True)
class SettingsView:
    default_output_directory: str
    default_preset_id: str
    concurrent_downloads: int
    default_audio_preset_id: str = "audio.best.original.auto"
    theme: str = "system"
    language: str = "en"
    startup_check_seen: bool = False


@dataclass(frozen=True, slots=True)
class DependencyStatusView:
    component: str
    state: str
    version: str | None
    message_key: str


def media_view(configuration_id: str, media: MediaInfo) -> MediaConfigurationView:
    playlist_count = media.playlist.item_count if media.playlist is not None else None
    return MediaConfigurationView(
        configuration_id=configuration_id,
        source_url=str(media.source_url),
        title=media.title,
        source_name=media.source_name,
        uploader=media.uploader,
        duration_seconds=media.duration_seconds,
        thumbnail_url=str(media.thumbnail_url) if media.thumbnail_url is not None else None,
        is_live=media.is_live,
        playlist_item_count=playlist_count,
        presets=_preset_views(media),
    )


def task_item_view(
    task: DownloadTask,
    *,
    recovery_store: RecoveryStore,
    output_files: OutputFileInspector,
) -> DownloadItemView:
    attempt = task.current_attempt
    progress = attempt.progress
    progress_view = (
        ProgressView(
            stage=progress.stage.value,
            fraction=progress.fraction,
            downloaded_bytes=progress.downloaded_bytes,
            total_bytes=progress.total_bytes,
            speed_bytes_per_second=progress.speed_bytes_per_second,
            eta_seconds=progress.eta_seconds,
        )
        if progress is not None
        else None
    )
    kind, quality, container = preset_fields(task.request.preset)
    return DownloadItemView(
        task_id=str(task.task_id),
        attempt_id=str(attempt.attempt_id),
        title=task.request.media_title,
        preset_kind=kind,
        quality=quality,
        container=container,
        status=DownloadStatus(
            task.state.value if task.state is not TaskState.QUEUED else "waiting"
        ),
        created_at=task.created_at.value,
        updated_at=attempt.updated_at.value,
        progress=progress_view,
        failure=message_for_failure(attempt.failure) if attempt.failure is not None else None,
        output_path=str(attempt.output_path) if attempt.output_path is not None else None,
        actions=_actions(task, recovery_store=recovery_store, output_files=output_files),
    )


def task_details_view(
    task: DownloadTask,
    *,
    recovery_store: RecoveryStore,
    output_files: OutputFileInspector,
) -> TaskDetailsView:
    return TaskDetailsView(
        item=task_item_view(task, recovery_store=recovery_store, output_files=output_files),
        source_url=str(task.request.source_url),
        output_directory=str(task.request.output_directory),
        attempts=tuple(
            AttemptView(
                attempt_id=str(attempt.attempt_id),
                number=attempt.number,
                status=DownloadStatus(
                    attempt.state.value if attempt.state is not TaskState.QUEUED else "waiting"
                ),
                created_at=attempt.created_at.value,
                updated_at=attempt.updated_at.value,
                finished_at=attempt.finished_at.value if attempt.finished_at is not None else None,
                failure=message_for_failure(attempt.failure)
                if attempt.failure is not None
                else None,
            )
            for attempt in task.attempts
        ),
    )


def downloads_view(
    tasks: tuple[DownloadTask, ...],
    *,
    recovery_store: RecoveryStore,
    output_files: OutputFileInspector,
) -> DownloadsView:
    items = tuple(
        task_item_view(task, recovery_store=recovery_store, output_files=output_files)
        for task in tasks
    )
    return DownloadsView(
        DownloadSummaryView(
            active=sum(
                task.state in {TaskState.DOWNLOADING, TaskState.PROCESSING} for task in tasks
            ),
            queued=sum(task.state is TaskState.QUEUED for task in tasks),
            completed=sum(task.state is TaskState.COMPLETED for task in tasks),
            failed=sum(task.state is TaskState.FAILED for task in tasks),
        ),
        items,
    )


def history_view(
    tasks: tuple[DownloadTask, ...],
    *,
    recovery_store: RecoveryStore,
    output_files: OutputFileInspector,
) -> tuple[HistoryItemView, ...]:
    history: list[HistoryItemView] = []
    for task in tasks:
        attempt = task.current_attempt
        if attempt.finished_at is None:
            continue
        item = task_item_view(task, recovery_store=recovery_store, output_files=output_files)
        history.append(
            HistoryItemView(
                task_id=item.task_id,
                title=item.title,
                status=item.status,
                preset_kind=item.preset_kind,
                quality=item.quality,
                container=item.container,
                finished_at=attempt.finished_at.value,
                output_path=item.output_path,
                failure=item.failure,
                actions=item.actions,
            )
        )
    return tuple(history)


def dependency_views(report: DependencyReport) -> tuple[DependencyStatusView, ...]:
    return tuple(
        DependencyStatusView(
            component=item.component.value,
            state=item.state.value,
            version=item.version,
            message_key=(
                f"dependency.{item.component.value}.ready"
                if item.state is DependencyState.READY
                else f"dependency.{item.component.value}.unavailable"
            ),
        )
        for item in report.dependencies
    )


def preset_id(preset: DownloadPreset) -> str:
    kind, quality, container = preset_fields(preset)
    fps = preset.preferred_frames_per_second if isinstance(preset, VideoPreset) else None
    return f"{kind.value}.{quality}.{container}.{fps or 'auto'}"


def preset_fields(preset: DownloadPreset) -> tuple[MediaKind, str, str]:
    if isinstance(preset, VideoPreset):
        return MediaKind.VIDEO, preset.quality.value, preset.container.value
    return MediaKind.AUDIO, preset.quality.value, preset.container.value


def _preset_views(media: MediaInfo) -> tuple[PresetOptionView, ...]:
    from mediaflow.application.format_availability import check_preset_availability

    presets: tuple[DownloadPreset, ...] = (
        *(
            VideoPreset(quality, container)
            for quality in VideoQuality
            for container in VideoContainer
        ),
        *(AudioPreset(container=container) for container in AudioContainer),
    )
    views = []
    for preset in presets:
        availability = check_preset_availability(media, preset)
        kind, quality, container = preset_fields(preset)
        views.append(
            PresetOptionView(
                preset_id=preset_id(preset),
                kind=kind,
                quality=quality,
                container=container,
                frames_per_second=(
                    preset.preferred_frames_per_second if isinstance(preset, VideoPreset) else None
                ),
                available=availability.available,
                unavailable_reason_key=(
                    f"preset.unavailable.{availability.issue.value}"
                    if availability.issue is not None
                    else None
                ),
                requires_processing=isinstance(preset, AudioPreset),
            )
        )
    return tuple(views)


def _actions(
    task: DownloadTask,
    *,
    recovery_store: RecoveryStore,
    output_files: OutputFileInspector,
) -> TaskActionsView:
    attempt = task.current_attempt
    processing_failure = (
        task.state is TaskState.FAILED
        and attempt.failure is not None
        and attempt.failure.code.startswith("processing.")
    )
    resumable = False
    if task.state is TaskState.INTERRUPTED:
        if attempt.interrupted_from is TaskState.PROCESSING:
            resumable = recovery_store.load_processing_artifact(task) is not None
        else:
            resumable = recovery_store.has_resumable_partial(task)
    retry_processing = (
        processing_failure
        and attempt.failure is not None
        and attempt.failure.retryable
        and recovery_store.load_processing_artifact(task) is not None
    )
    can_retry = task.state is TaskState.CANCELLED or (
        task.state is TaskState.FAILED
        and attempt.failure is not None
        and attempt.failure.retryable
        and not processing_failure
    )
    can_open = (
        task.state is TaskState.COMPLETED
        and attempt.output_path is not None
        and output_files.exists(attempt.output_path)
    )
    return TaskActionsView(
        can_cancel=task.state
        in {
            TaskState.QUEUED,
            TaskState.DOWNLOADING,
            TaskState.PROCESSING,
            TaskState.PAUSED,
            TaskState.INTERRUPTED,
        },
        can_retry=can_retry,
        can_resume=resumable,
        can_restart=task.state is TaskState.INTERRUPTED,
        can_retry_processing=retry_processing,
        can_open_output=can_open,
    )
