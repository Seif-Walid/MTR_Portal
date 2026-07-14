"""Shared schema field types."""

import re
from typing import Annotated

from pydantic import AfterValidator

# permissive on purpose: internal domains like user@org.local must work,
# which the email-validator package rejects as special-use names
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_RE.match(value):
        raise ValueError("Invalid email address")
    return value


Email = Annotated[str, AfterValidator(_normalize_email)]
