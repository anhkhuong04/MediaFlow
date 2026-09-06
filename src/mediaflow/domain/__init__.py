"""Public, framework-independent domain API."""

from mediaflow.domain.analysis import AnalysisOperation, AnalysisState, InvalidAnalysisTransition
from mediaflow.domain.errors import Failure, FailureCategory
from mediaflow.domain.identifiers import AttemptId, OutputPath, SourceUrl, TaskId, UtcTimestamp
from mediaflow.domain.media import (
    AudioContainer,
    AudioPreset,
    AudioQuality,
    DownloadPreset,
    MediaInfo,
    MediaStream,
    StreamKind,
    VideoContainer,
    VideoPreset,
    VideoQuality,
)
from mediaflow.domain.progress import ProgressSnapshot, ProgressStage
from mediaflow.domain.tasks import (
    TERMINAL_STATES,
    DownloadAttempt,
    DownloadRequest,
    DownloadTask,
    InvalidTaskTransition,
    TaskState,
    allowed_transitions,
    is_transition_allowed,
)

__all__ = [
    "TERMINAL_STATES",
    "AnalysisOperation",
    "AnalysisState",
    "AttemptId",
    "AudioContainer",
    "AudioPreset",
    "AudioQuality",
    "DownloadAttempt",
    "DownloadPreset",
    "DownloadRequest",
    "DownloadTask",
    "Failure",
    "FailureCategory",
    "InvalidAnalysisTransition",
    "InvalidTaskTransition",
    "MediaInfo",
    "MediaStream",
    "OutputPath",
    "ProgressSnapshot",
    "ProgressStage",
    "SourceUrl",
    "StreamKind",
    "TaskId",
    "TaskState",
    "UtcTimestamp",
    "VideoContainer",
    "VideoPreset",
    "VideoQuality",
    "allowed_transitions",
    "is_transition_allowed",
]
