"""Shared exceptions for article-source services (PubMed, Europe PMC, ...)."""

from __future__ import annotations


class SourceError(RuntimeError):
    """A source could not be reached or returned an unusable response."""


class ArticleNotFound(SourceError):
    """A requested article id resolved to no record."""
