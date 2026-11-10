"""
Shared API schema pieces: pagination, simple messages and metadata validation.
"""

# Standard library imports
import json
import re
from typing import Any, Dict, Generic, List, TypeVar

# Third-party imports
from pydantic import BaseModel, ConfigDict

ItemT = TypeVar("ItemT")

#: Admin-editable metadata limits: keys, key syntax and serialized size.
MAX_METADATA_KEYS = 30
MAX_METADATA_BYTES = 4096
METADATA_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class ApiModel(BaseModel):
    """Base for response models built from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[ItemT]):
    """One page of a list endpoint."""

    items: List[ItemT]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    """A plain confirmation message."""

    message: str


def _is_scalar(value: Any) -> bool:
    """JSON scalar (string, number, boolean or null)."""
    return value is None or isinstance(value, (str, int, float, bool))


def validate_metadata(value: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept flat metadata: identifier-like keys, scalar or list-of-scalar values.

    Raises:
        ValueError: The metadata is too large or not flat.
    """
    if len(value) > MAX_METADATA_KEYS:
        raise ValueError(f"metadata may have at most {MAX_METADATA_KEYS} keys")
    for key, item in value.items():
        if not METADATA_KEY_PATTERN.match(key):
            raise ValueError(f"invalid metadata key '{key}' (letters, digits and _ only)")
        if not (_is_scalar(item) or (isinstance(item, list) and all(_is_scalar(v) for v in item))):
            raise ValueError(f"metadata '{key}' must be a text/number/boolean or a list of them")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata must be under {MAX_METADATA_BYTES} bytes")
    return value
