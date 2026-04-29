"""Exception hierarchy for release-flow.

All custom exceptions inherit from ReleaseFlowError so callers can catch
the whole family with a single except clause.
"""


class ReleaseFlowError(Exception):
    """Base for all release-flow errors."""


class ConfigError(ReleaseFlowError):
    """Config file missing, malformed, or invalid."""


class ProjectDetectionError(ReleaseFlowError):
    """Cannot determine project type (no marker file matched)."""


class VersionParseError(ReleaseFlowError):
    """Cannot parse version string from primary file."""


class VersionMismatchError(ReleaseFlowError):
    """Version in primary differs from one or more secondary files."""


class GitError(ReleaseFlowError):
    """Git command failed."""


class GitLabError(ReleaseFlowError):
    """GitLab API error (4xx/5xx, network)."""


class ProtectedBranchError(ReleaseFlowError):
    """Attempted forbidden operation on a protected branch.

    HARD-CODED INVARIANT: never bypassable by any flag or config.
    """


class FlowError(ReleaseFlowError):
    """Orchestrator detected an unrecoverable flow inconsistency."""


class RecoveryError(ReleaseFlowError):
    """Recovery sub-flow failed or was declined by user."""


class UserAbortError(ReleaseFlowError):
    """User declined a confirmation prompt."""
