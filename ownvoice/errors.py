"""Shared exit codes and diagnostics."""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    INTERNAL = 1
    OPERATOR = 2
    DEPENDENCY = 3
    LINT = 4
    GUARD = 5


class DiagnosticError(Exception):
    def __init__(
        self,
        operation,
        identity,
        observed,
        expected,
        cause,
        next_step,
        *,
        exit_code=ExitCode.OPERATOR,
    ):
        self.operation = operation
        self.identity = identity
        self.observed = observed
        self.expected = expected
        self.cause = cause
        self.next_step = next_step
        self.exit_code = exit_code
        if isinstance(cause, BaseException):
            self.__cause__ = cause
        super().__init__(str(self))

    def __str__(self):
        cause = f"; caused by: {self.cause}" if self.cause is not None else ""
        return (
            f"{self.operation} [{self.identity}]: {self.observed}; "
            f"expected {self.expected}{cause}; next step: {self.next_step}"
        )


class ValidationErrors(Exception):
    """All boundary failures, in input order."""

    def __init__(self, errors):
        self.errors = tuple(errors)
        self.exit_code = max((e.exit_code for e in self.errors), default=ExitCode.OPERATOR)
        super().__init__("\n".join(map(str, self.errors)))


def internal_error(operation, identity, cause):
    return DiagnosticError(
        f"internal error (this is a bug): {operation}",
        identity,
        f"{type(cause).__name__}: {cause}",
        "successful command execution",
        cause,
        "please report with --verbose output",
        exit_code=ExitCode.INTERNAL,
    )


def not_implemented(command):
    raise DiagnosticError(
        "run command",
        command,
        "not implemented yet",
        "an implemented command",
        None,
        "install a version implementing this command",
        exit_code=ExitCode.INTERNAL,
    )
