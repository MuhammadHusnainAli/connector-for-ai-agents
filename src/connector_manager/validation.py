"""Validation of user-supplied values against a connector's auth schema."""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .errors import ValidationError
from .models import AuthField, AuthSchema, FieldGroup

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9._-]*[a-zA-Z0-9])?$")


def validate(
    schema: AuthSchema,
    credentials: Mapping[str, Any] | None = None,
    connection_config: Mapping[str, Any] | None = None,
    integration_config: Mapping[str, Any] | None = None,
    require_all: bool = True,
) -> dict[str, dict[str, Any]]:
    """Validate inputs and return them normalised, grouped by destination.

    Raises :class:`~connector_manager.errors.ValidationError` listing every
    offending field, so a UI can show all problems at once.

    ``require_all=False`` skips the "missing required field" checks, which is
    what refresh flows want (they only re-validate what is present).
    """
    supplied = {
        FieldGroup.CREDENTIALS: dict(credentials or {}),
        FieldGroup.CONNECTION_CONFIG: dict(connection_config or {}),
        FieldGroup.INTEGRATION_CONFIG: dict(integration_config or {}),
        FieldGroup.ASSERTION_OPTION: {},
    }
    errors: dict[str, str] = {}
    out: dict[FieldGroup, dict[str, Any]] = {group: {} for group in supplied}

    field_groups = {
        FieldGroup.CREDENTIALS: schema.credentials,
        FieldGroup.CONNECTION_CONFIG: schema.connection_config,
        FieldGroup.INTEGRATION_CONFIG: schema.integration_config,
        FieldGroup.ASSERTION_OPTION: schema.assertion_option,
    }

    for group, fields in field_groups.items():
        values = supplied[group]
        for field in fields:
            raw = values.get(field.name)
            if raw in (None, "") and field.default_value is not None:
                # Providers use a default (often an empty string, e.g. the unused
                # username half of an api-key-over-basic pair) instead of asking.
                out[group][field.name] = field.default_value
                continue

            if raw in (None, ""):
                if (
                    field.required
                    and require_all
                    and not field.automated
                    and not field.hidden
                    and not _is_hidden_conditional(field, values)
                ):
                    errors[field.name] = f"{field.title or field.name} is required"
                continue

            value = raw if not isinstance(raw, (int, float, bool)) else str(raw)
            if not isinstance(value, str):
                out[group][field.name] = raw
                continue

            problem = _check(field, value)
            if problem:
                errors[field.name] = problem
                continue
            out[group][field.name] = value

        # Keep extra values the provider template may still reference.
        for key, value in values.items():
            if key not in out[group]:
                out[group][key] = value

    if errors:
        raise ValidationError(
            f"Invalid input for connector '{schema.connector_id}': {', '.join(sorted(errors))}",
            errors,
        )

    return {group.value: values for group, values in out.items()}


def _is_hidden_conditional(field: AuthField, values: Mapping[str, Any]) -> bool:
    """``visible_when`` fields are only required when their condition holds."""
    condition = field.visible_when
    if not condition:
        return False
    return str(values.get(condition.get("field", ""), "")) != condition.get("equals")


def _check(field: AuthField, value: str) -> str | None:
    if field.enum and value not in field.enum:
        return f"{field.title or field.name} must be one of: {', '.join(field.enum)}"

    if field.pattern:
        try:
            if not re.search(field.pattern, value):
                return f"{field.title or field.name} does not match the expected format"
        except re.error:
            # A provider pattern we cannot compile must not block the connection.
            pass

    if field.format == "email" and not _EMAIL_RE.match(value):
        return f"{field.title or field.name} must be a valid email address"
    if field.format == "uuid" and not _UUID_RE.match(value):
        return f"{field.title or field.name} must be a valid UUID"
    if field.format == "hostname" and not _HOSTNAME_RE.match(value):
        return f"{field.title or field.name} must be a valid hostname (no scheme or path)"
    if field.format == "uri":
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return f"{field.title or field.name} must be a valid URL"
    return None
