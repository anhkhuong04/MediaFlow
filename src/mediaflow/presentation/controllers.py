"""Thin UI-thread controllers that project C8 read models and emit user intent results."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from PySide6.QtCore import QObject, Signal

from mediaflow.application import (
    ApplicationEvent,
    CommandResult,
    DownloadItemView,
    DownloadSummaryView,
    DownloadsView,
    HistoryItemView,
    MediaConfigurationView,
    OutputReady,
    SettingsView,
    TaskDetailsView,
    TaskFailed,
    TaskProgressChanged,
    TaskQueued,
    TaskStateChanged,
    UserMessage,
)
from mediaflow.presentation.bridge import (
    CommandCompletion,
    CommandKey,
    PresentationCommandRunner,
    QtEventBridge,
)
from mediaflow.presentation.contracts import PresentationFacade
from mediaflow.presentation.window import assert_ui_thread


@dataclass(frozen=True, slots=True)
class CommandState:
    """Busy/error state for exactly one user action, never an exception payload."""

    is_busy: bool = False
    error: UserMessage | None = None


@dataclass(frozen=True, slots=True)
class HomeState:
    """View state needed by the upcoming Home workflow."""

    analysis: CommandState = CommandState()
    enqueue: CommandState = CommandState()
    configuration: MediaConfigurationView | None = None
    active_analysis_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadsState:
    """Stable-ID collection state; widgets can preserve selection and scroll by task ID."""

    items: tuple[DownloadItemView, ...] = ()
    selected_task_id: str | None = None
    refresh: CommandState = CommandState()
    action_states: tuple[TaskActionState, ...] = ()
    summary: DownloadSummaryView = DownloadSummaryView(0, 0, 0, 0)


class TaskAction(StrEnum):
    """Honest task actions exposed only through the core facade capability contract."""

    CANCEL = "cancel"
    RETRY = "retry"
    RESUME = "resume"
    RESTART = "restart"
    RETRY_PROCESSING = "retry_processing"


@dataclass(frozen=True, slots=True)
class TaskActionState:
    """Command state associated with a stable task ID rather than a row position."""

    task_id: str
    action: TaskAction
    state: CommandState


@dataclass(frozen=True, slots=True)
class HistoryState:
    """Read-only state for the future History screen."""

    items: tuple[HistoryItemView, ...] = ()
    refresh: CommandState = CommandState()


@dataclass(frozen=True, slots=True)
class SettingsState:
    """Read model and command state for the future Settings screen."""

    settings: SettingsView | None = None
    load: CommandState = CommandState()
    save: CommandState = CommandState()


class HomeController(QObject):
    """Project analysis/enqueue result state without exposing facade calls to widgets."""

    state_changed = Signal(object)
    _ANALYZE = CommandKey("home", "analyze")
    _ENQUEUE = CommandKey("home", "enqueue")

    def __init__(
        self,
        facade: PresentationFacade,
        bridge: QtEventBridge,
        runner: PresentationCommandRunner,
    ) -> None:
        super().__init__()
        self._facade = facade
        self._bridge = bridge
        self._runner = runner
        self._state = HomeState()

    @property
    def state(self) -> HomeState:
        return self._state

    def analyze(self, source_url: str) -> bool:
        """Start one facade-owned analysis future; a repeat click is ignored while busy."""

        assert_ui_thread(self)
        if self._state.analysis.is_busy:
            return False
        request = self._facade.analyze(source_url)
        self._state = replace(
            self._state,
            analysis=CommandState(is_busy=True),
            active_analysis_request_id=request.request_id,
        )
        self.state_changed.emit(self._state)
        self._bridge.observe_future(self._ANALYZE, request.result)
        return True

    def cancel_analysis(self) -> bool:
        """Forward cancellation only for the facade's current opaque request ID."""

        assert_ui_thread(self)
        request_id = self._state.active_analysis_request_id
        return request_id is not None and self._facade.cancel_analysis(request_id)

    def enqueue(self, *, preset_id: str, output_directory: str) -> bool:
        """Schedule queueing away from UI and reject repeat intent while pending."""

        assert_ui_thread(self)
        configuration = self._state.configuration
        if configuration is None or self._state.enqueue.is_busy:
            return False
        submitted = self._runner.submit(
            self._ENQUEUE,
            lambda: self._facade.enqueue(
                configuration_id=configuration.configuration_id,
                preset_id_value=preset_id,
                output_directory=output_directory,
            ),
        )
        if submitted:
            self._state = replace(self._state, enqueue=CommandState(is_busy=True))
            self.state_changed.emit(self._state)
        return submitted

    def handle_completion(self, completion: CommandCompletion) -> None:
        assert_ui_thread(self)
        if completion.key == self._ANALYZE:
            configuration = (
                completion.result.value
                if isinstance(completion.result.value, MediaConfigurationView)
                else None
            )
            self._state = replace(
                self._state,
                analysis=CommandState(error=completion.result.error),
                configuration=configuration,
                active_analysis_request_id=None,
            )
            self.state_changed.emit(self._state)
        elif completion.key == self._ENQUEUE:
            self._runner.release(completion.key)
            self._state = replace(self._state, enqueue=CommandState(error=completion.result.error))
            self.state_changed.emit(self._state)


class DownloadsController(QObject):
    """Keep download rows keyed by task ID so one event never rebuilds the full collection."""

    state_changed = Signal(object)
    _REFRESH = CommandKey("downloads", "refresh")

    def __init__(self, facade: PresentationFacade, runner: PresentationCommandRunner) -> None:
        super().__init__()
        self._facade = facade
        self._runner = runner
        self._state = DownloadsState()
        self._items_by_id: dict[str, DownloadItemView] = {}
        self._ordered_ids: list[str] = []
        self._task_revisions: dict[str, int] = {}
        self._inflight_revisions: dict[str, int] = {}
        self._action_states: dict[CommandKey, CommandState] = {}

    @property
    def state(self) -> DownloadsState:
        return self._state

    def refresh(self) -> bool:
        """Load the initial projection in the presentation worker, not a widget callback."""

        assert_ui_thread(self)
        if self._state.refresh.is_busy:
            return False
        submitted = self._runner.submit(
            self._REFRESH, lambda: CommandResult.succeeded(self._facade.downloads())
        )
        if submitted:
            self._state = replace(self._state, refresh=CommandState(is_busy=True))
            self.state_changed.emit(self._state)
        return submitted

    def select_task(self, task_id: str | None) -> None:
        """Persist selection by stable ID; individual row updates do not clear it."""

        assert_ui_thread(self)
        selected = task_id if task_id in self._items_by_id else None
        if selected != self._state.selected_task_id:
            self._state = replace(self._state, selected_task_id=selected)
            self.state_changed.emit(self._state)

    def handle_event(self, event: ApplicationEvent) -> None:
        """Request a targeted authoritative row refresh for one task only."""

        assert_ui_thread(self)
        task_id = _task_id_for_event(event)
        if task_id is None:
            return
        revision = self._task_revisions.get(task_id, 0) + 1
        self._task_revisions[task_id] = revision
        self._schedule_task_refresh(task_id)

    def invoke_action(self, task_id: str, action: TaskAction) -> bool:
        """Run one task action once; busy/error state is retained by task ID and action."""

        assert_ui_thread(self)
        key = CommandKey("downloads", f"action:{action.value}", task_id)
        if self._action_states.get(key, CommandState()).is_busy:
            return False
        operation = {
            TaskAction.CANCEL: self._facade.cancel,
            TaskAction.RETRY: self._facade.retry,
            TaskAction.RESUME: self._facade.resume,
            TaskAction.RESTART: self._facade.restart,
            TaskAction.RETRY_PROCESSING: self._facade.retry_processing,
        }[action]
        submitted = self._runner.submit(key, lambda: operation(task_id))
        if submitted:
            self._action_states[key] = CommandState(is_busy=True)
            self._emit_state()
        return submitted

    def handle_completion(self, completion: CommandCompletion) -> None:
        """Apply one completion on UI thread and retain any event that raced with it."""

        assert_ui_thread(self)
        if completion.key == self._REFRESH:
            self._runner.release(completion.key)
            if isinstance(completion.result.value, DownloadsView):
                self._replace_all(completion.result.value)
            self._state = replace(self._state, refresh=CommandState(error=completion.result.error))
            self.state_changed.emit(self._state)
            return
        if completion.key.screen != "downloads":
            return
        if completion.key.action.startswith("action:"):
            self._runner.release(completion.key)
            self._action_states[completion.key] = CommandState(error=completion.result.error)
            if isinstance(completion.result.value, DownloadItemView):
                self._upsert(completion.result.value, emit=False)
            self._emit_state()
            return
        if completion.key.action != "task_refresh":
            return
        task_id = completion.key.subject_id
        if task_id is None:
            return
        started_revision = self._inflight_revisions.pop(task_id, 0)
        self._runner.release(completion.key)
        if isinstance(completion.result.value, TaskDetailsView):
            self._upsert(completion.result.value.item)
        if self._task_revisions.get(task_id, 0) > started_revision:
            self._schedule_task_refresh(task_id)

    def _schedule_task_refresh(self, task_id: str) -> None:
        if task_id in self._inflight_revisions:
            return
        key = CommandKey("downloads", "task_refresh", task_id)
        revision = self._task_revisions[task_id]
        submitted = self._runner.submit(key, lambda: self._facade.task_details(task_id))
        if submitted:
            self._inflight_revisions[task_id] = revision

    def _replace_all(self, view: DownloadsView) -> None:
        self._items_by_id = {item.task_id: item for item in view.items}
        self._ordered_ids = [item.task_id for item in view.items]
        selected_task_id = self._state.selected_task_id
        if selected_task_id not in self._items_by_id:
            selected_task_id = None
        self._state = replace(
            self._state,
            items=view.items,
            selected_task_id=selected_task_id,
            summary=view.summary,
        )

    def _upsert(self, item: DownloadItemView, *, emit: bool = True) -> None:
        if item.task_id not in self._items_by_id:
            self._ordered_ids.append(item.task_id)
        self._items_by_id[item.task_id] = item
        self._state = replace(
            self._state,
            items=tuple(self._items_by_id[task_id] for task_id in self._ordered_ids),
        )
        if emit:
            self._emit_state()

    def _emit_state(self) -> None:
        action_states = tuple(
            TaskActionState(
                task_id=key.subject_id or "",
                action=TaskAction(key.action.removeprefix("action:")),
                state=state,
            )
            for key, state in self._action_states.items()
        )
        self._state = replace(self._state, action_states=action_states)
        self.state_changed.emit(self._state)


class HistoryController(QObject):
    """Maintain a core-projected history state for G5 without task-row assumptions."""

    state_changed = Signal(object)
    _REFRESH = CommandKey("history", "refresh")

    def __init__(self, facade: PresentationFacade, runner: PresentationCommandRunner) -> None:
        super().__init__()
        self._facade = facade
        self._runner = runner
        self._state = HistoryState()
        self._refresh_requested_while_busy = False

    @property
    def state(self) -> HistoryState:
        return self._state

    def refresh(self) -> bool:
        assert_ui_thread(self)
        if self._state.refresh.is_busy:
            self._refresh_requested_while_busy = True
            return False
        submitted = self._runner.submit(
            self._REFRESH, lambda: CommandResult.succeeded(self._facade.history())
        )
        if submitted:
            self._state = replace(self._state, refresh=CommandState(is_busy=True))
            self.state_changed.emit(self._state)
        return submitted

    def handle_event(self, event: ApplicationEvent) -> None:
        assert_ui_thread(self)
        if isinstance(event, (OutputReady, TaskFailed)):
            self.refresh()

    def handle_completion(self, completion: CommandCompletion) -> None:
        assert_ui_thread(self)
        if completion.key != self._REFRESH:
            return
        self._runner.release(completion.key)
        history = completion.result.value
        if isinstance(history, tuple) and all(
            isinstance(item, HistoryItemView) for item in history
        ):
            self._state = replace(self._state, items=history)
        self._state = replace(self._state, refresh=CommandState(error=completion.result.error))
        self.state_changed.emit(self._state)
        if self._refresh_requested_while_busy:
            self._refresh_requested_while_busy = False
            self.refresh()


class SettingsController(QObject):
    """Project settings reads/saves with explicit busy state for the future Settings screen."""

    state_changed = Signal(object)
    _LOAD = CommandKey("settings", "load")
    _SAVE = CommandKey("settings", "save")

    def __init__(self, facade: PresentationFacade, runner: PresentationCommandRunner) -> None:
        super().__init__()
        self._facade = facade
        self._runner = runner
        self._state = SettingsState()

    @property
    def state(self) -> SettingsState:
        return self._state

    def load(self) -> bool:
        assert_ui_thread(self)
        if self._state.load.is_busy:
            return False
        submitted = self._runner.submit(
            self._LOAD, lambda: CommandResult.succeeded(self._facade.load_settings())
        )
        if submitted:
            self._state = replace(self._state, load=CommandState(is_busy=True))
            self.state_changed.emit(self._state)
        return submitted

    def save(
        self, *, default_output_directory: str, default_preset_id: str, concurrent_downloads: int
    ) -> bool:
        assert_ui_thread(self)
        if self._state.save.is_busy:
            return False
        submitted = self._runner.submit(
            self._SAVE,
            lambda: self._facade.save_settings(
                default_output_directory=default_output_directory,
                default_preset_id=default_preset_id,
                concurrent_downloads=concurrent_downloads,
            ),
        )
        if submitted:
            self._state = replace(self._state, save=CommandState(is_busy=True))
            self.state_changed.emit(self._state)
        return submitted

    def handle_completion(self, completion: CommandCompletion) -> None:
        assert_ui_thread(self)
        if completion.key not in {self._LOAD, self._SAVE}:
            return
        self._runner.release(completion.key)
        settings = completion.result.value
        if isinstance(settings, SettingsView):
            self._state = replace(self._state, settings=settings)
        if completion.key == self._LOAD:
            self._state = replace(self._state, load=CommandState(error=completion.result.error))
        else:
            self._state = replace(self._state, save=CommandState(error=completion.result.error))
        self.state_changed.emit(self._state)


def _task_id_for_event(event: ApplicationEvent) -> str | None:
    if isinstance(
        event, (TaskQueued, TaskStateChanged, TaskProgressChanged, TaskFailed, OutputReady)
    ):
        return str(event.task_id)
    return None
