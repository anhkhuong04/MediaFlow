"""Stable, localizable messages exposed to presentation clients."""

from dataclasses import dataclass
from enum import StrEnum

from mediaflow.domain import Failure, FailureCategory


class SuggestedAction(StrEnum):
    NONE = "none"
    RETRY = "retry"
    RETRY_PROCESSING = "retry_processing"
    CHOOSE_FOLDER = "choose_folder"
    CONFIGURE_DEPENDENCY = "configure_dependency"
    VIEW_DETAILS = "view_details"


@dataclass(frozen=True, slots=True)
class UserMessage:
    """Translation keys plus a sanitized diagnostic code, never raw engine text."""

    title_key: str
    body_key: str
    technical_code: str
    suggested_action: SuggestedAction = SuggestedAction.NONE


_FAILURE_MESSAGES = {
    FailureCategory.INVALID_INPUT: ("error.invalid_url.title", "error.invalid_url.body"),
    FailureCategory.UNSUPPORTED_SOURCE: (
        "error.unsupported_source.title",
        "error.unsupported_source.body",
    ),
    FailureCategory.MEDIA_UNAVAILABLE: (
        "error.media_unavailable.title",
        "error.media_unavailable.body",
    ),
    FailureCategory.AUTH_REQUIRED: (
        "error.sign_in_required.title",
        "error.sign_in_required.body",
    ),
    FailureCategory.ACCESS_DENIED: (
        "error.access_not_permitted.title",
        "error.access_not_permitted.body",
    ),
    FailureCategory.NETWORK: ("error.network.title", "error.network.body"),
    FailureCategory.DISK_SPACE: ("error.disk_space.title", "error.disk_space.body"),
    FailureCategory.DEPENDENCY: ("error.dependency.title", "error.dependency.body"),
    FailureCategory.OUTPUT_CONFLICT: (
        "error.output_conflict.title",
        "error.output_conflict.body",
    ),
    FailureCategory.DOWNLOAD: ("error.download.title", "error.download.body"),
    FailureCategory.PROCESSING: ("error.processing.title", "error.processing.body"),
    FailureCategory.CANCELLED: ("status.cancelled.title", "status.cancelled.body"),
    FailureCategory.UNEXPECTED: ("error.unexpected.title", "error.unexpected.body"),
}


def message_for_failure(failure: Failure) -> UserMessage:
    title_key, body_key = _FAILURE_MESSAGES[failure.category]
    if failure.category is FailureCategory.PROCESSING and failure.retryable:
        action = SuggestedAction.RETRY_PROCESSING
    elif failure.category is FailureCategory.DISK_SPACE:
        action = SuggestedAction.CHOOSE_FOLDER
    elif failure.category is FailureCategory.DEPENDENCY:
        action = SuggestedAction.CONFIGURE_DEPENDENCY
    elif failure.retryable:
        action = SuggestedAction.RETRY
    elif failure.category in {
        FailureCategory.UNSUPPORTED_SOURCE,
        FailureCategory.MEDIA_UNAVAILABLE,
        FailureCategory.AUTH_REQUIRED,
        FailureCategory.ACCESS_DENIED,
        FailureCategory.UNEXPECTED,
    }:
        action = SuggestedAction.VIEW_DETAILS
    else:
        action = SuggestedAction.NONE
    return UserMessage(title_key, body_key, failure.code, action)


def command_message(code: str, *, action: SuggestedAction = SuggestedAction.NONE) -> UserMessage:
    """Map facade validation/command failures without exposing exception strings."""

    return UserMessage(f"{code}.title", f"{code}.body", code, action)
