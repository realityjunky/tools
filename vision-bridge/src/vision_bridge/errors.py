from __future__ import annotations


class VisionBridgeError(RuntimeError):
    """Base class for failures callers can distinguish without parsing text."""

    identity = "vision_bridge_error"


class ConfigurationError(VisionBridgeError):
    identity = "configuration_error"


class PathSafetyError(VisionBridgeError):
    """Base class for failures in local-file admission policy."""


class PathNotFound(PathSafetyError):
    identity = "not_found"


class ExtensionNotAllowed(PathSafetyError):
    identity = "extension_not_allowed"


class SecretPatternRefused(PathSafetyError):
    identity = "secret_pattern_refused"


class DirectoryNotAllowed(PathSafetyError):
    identity = "directory_not_allowed"


class FileTooLarge(PathSafetyError):
    identity = "file_too_large"


class RequestDeadlineExceeded(VisionBridgeError):
    identity = "request_deadline_exceeded"


class GatewayUnreachable(VisionBridgeError):
    identity = "gateway_unreachable"


class BudgetExhausted(VisionBridgeError):
    identity = "budget_exhausted"


class ModelError(VisionBridgeError):
    identity = "model_error"
