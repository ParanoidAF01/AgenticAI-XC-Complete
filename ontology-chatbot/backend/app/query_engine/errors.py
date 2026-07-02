"""Custom exception classes for the query engine pipeline."""

from __future__ import annotations


class AppError(Exception):
    pass


class OntologyProfileError(AppError):
    pass


class PlannerError(AppError):
    pass


class LLMError(AppError):
    pass


class SQLBuildError(AppError):
    pass


class SQLValidationError(AppError):
    pass


class SQLExecutionError(AppError):
    pass
