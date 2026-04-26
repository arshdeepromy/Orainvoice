"""Pydantic v2 schemas for the setup guide.

Request and response models for the setup guide endpoints.

**Validates: Requirements 2.3, 3.1**
"""

from __future__ import annotations

from pydantic import BaseModel


class SetupGuideQuestion(BaseModel):
    """A single module question returned by the questions endpoint."""

    slug: str
    display_name: str
    setup_question: str
    setup_question_description: str | None
    category: str
    dependencies: list[str]


class SetupGuideQuestionsResponse(BaseModel):
    """Wrapped list of setup guide questions."""

    questions: list[SetupGuideQuestion]
    total: int


class SetupGuideAnswer(BaseModel):
    """A single yes/no answer for a module."""

    slug: str
    enabled: bool


class SetupGuideSubmitRequest(BaseModel):
    """Submission payload containing all user answers."""

    answers: list[SetupGuideAnswer]


class SetupGuideSubmitResponse(BaseModel):
    """Response after processing setup guide answers."""

    completed: bool
    auto_enabled: list[str]  # dependency modules auto-enabled by ModuleService
    message: str
