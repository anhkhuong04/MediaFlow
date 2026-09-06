"""Immutable, framework-neutral events emitted after application decisions."""

from dataclasses import dataclass

from mediaflow.domain import (
    AttemptId,
    DownloadRequest,
    Failure,
    MediaInfo,
    OutputPath,
    ProgressSnapshot,
    SourceUrl,
    TaskId,
    TaskState,
    UtcTimestamp,
)


@dataclass(frozen=True, slots=True)
class AnalysisSucceeded:
    source_url: SourceUrl
    media: MediaInfo
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class AnalysisFailed:
    source_url: SourceUrl
    failure: Failure
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class TaskQueued:
    task_id: TaskId
    attempt_id: AttemptId
    request: DownloadRequest
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class TaskStateChanged:
    task_id: TaskId
    attempt_id: AttemptId
    previous_state: TaskState
    state: TaskState
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class TaskProgressChanged:
    task_id: TaskId
    attempt_id: AttemptId
    progress: ProgressSnapshot
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class OutputReady:
    task_id: TaskId
    attempt_id: AttemptId
    output_path: OutputPath
    occurred_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class TaskFailed:
    task_id: TaskId
    attempt_id: AttemptId
    failure: Failure
    occurred_at: UtcTimestamp


type ApplicationEvent = (
    AnalysisSucceeded
    | AnalysisFailed
    | TaskQueued
    | TaskStateChanged
    | TaskProgressChanged
    | OutputReady
    | TaskFailed
)
