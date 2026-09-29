"""
Validates the arguments an LLM passes to a SQL tool (TOOL-02) and turns them into SQL parameters.

The tool's ``args_schema`` is a JSON Schema subset: an object whose properties
are ``string`` / ``integer`` / ``number`` / ``boolean`` with ``enum``,
``minimum``/``maximum``, ``minLength``/``maxLength``, ``pattern`` and
``format``. Extra properties are refused. Formats:

* ``date``: an ISO date.
* ``vn-period``: a period such as "tháng trước" or "quý 3", bound as
  ``:<name>_start`` / ``:<name>_end`` (end exclusive).
* ``vn-amount``: a money amount such as "1.000.000 đ".
"""

# Standard library imports
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

# Third-party imports
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

# Local imports
from utils.vietnamese_parsing import parse_amount, parse_period

#: Bound by the executor from the verified caller; never a tool argument (Invariant 1).
RESERVED_PARAMETERS = frozenset({"user_id"})
FORMAT_PERIOD = "vn-period"
FORMAT_AMOUNT = "vn-amount"
FORMAT_DATE = "date"
_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}
#: Longest string any tool argument may hold, whatever the schema says.
MAX_STRING_LENGTH = 200


class ToolArgumentsError(ValueError):
    """Arguments or schema are invalid; the message is safe to show the model."""


class ToolArguments:
    """A compiled ``args_schema``."""

    def __init__(self, schema: Dict[str, Any]):
        """
        Raises:
            ToolArgumentsError: The schema uses an unsupported shape or a reserved name.
        """
        if schema.get("type") != "object":
            raise ToolArgumentsError("args_schema must describe an object")
        self._schema = schema
        self._properties: Dict[str, Dict[str, Any]] = schema.get("properties", {})
        reserved = RESERVED_PARAMETERS & set(self._properties)
        if reserved:
            raise ToolArgumentsError(f"reserved argument names: {', '.join(sorted(reserved))}")
        required = set(schema.get("required", []))
        fields = {name: self._field(name, spec, name in required) for name, spec in self._properties.items()}
        self._model = create_model("ToolArgs", __config__=ConfigDict(extra="forbid", strict=False), **fields)

    @staticmethod
    def _field(name: str, spec: Dict[str, Any], required: bool) -> Tuple[Any, Any]:
        """A pydantic field for one JSON Schema property."""
        kind = spec.get("type")
        if kind not in _TYPES:
            raise ToolArgumentsError(f"argument {name!r}: unsupported type {kind!r}")
        annotation: Any = _TYPES[kind]
        if "enum" in spec:
            annotation = Literal[tuple(spec["enum"])]
        constraints: Dict[str, Any] = {}
        if kind == "string":
            constraints["max_length"] = min(int(spec.get("maxLength", MAX_STRING_LENGTH)), MAX_STRING_LENGTH)
            if "minLength" in spec:
                constraints["min_length"] = int(spec["minLength"])
            if "pattern" in spec:
                constraints["pattern"] = spec["pattern"]
        if kind in ("integer", "number"):
            if "minimum" in spec:
                constraints["ge"] = spec["minimum"]
            if "maximum" in spec:
                constraints["le"] = spec["maximum"]
        if not required:
            annotation = Optional[annotation]
        return annotation, Field(... if required else None, **constraints)

    @property
    def parameter_names(self) -> List[str]:
        """Every SQL parameter these arguments can produce."""
        names = []
        for name, spec in self._properties.items():
            if spec.get("format") == FORMAT_PERIOD:
                names += [f"{name}_start", f"{name}_end"]
            else:
                names.append(name)
        return names

    def parse(self, arguments: Dict[str, Any], today: Callable[[], date]) -> Dict[str, Any]:
        """
        Validate ``arguments`` and return SQL parameters (optional arguments default to ``None``).

        Raises:
            ToolArgumentsError: Describing every invalid argument.
        """
        try:
            validated: BaseModel = self._model.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, error['loc'])) or 'arguments'}: {error['msg']}" for error in exc.errors())
            raise ToolArgumentsError(problems) from exc
        parameters: Dict[str, Any] = {}
        for name, spec in self._properties.items():
            value = getattr(validated, name)
            fmt = spec.get("format")
            if fmt == FORMAT_PERIOD:
                period = parse_period(value, today()) if value is not None else None
                if value is not None and period is None:
                    raise ToolArgumentsError(f"{name}: not a period I understand (e.g. 'tháng trước', 'quý 3', '2026-01-01..2026-03-31')")
                parameters[f"{name}_start"], parameters[f"{name}_end"] = period if period else (None, None)
            elif fmt == FORMAT_AMOUNT and value is not None:
                amount = parse_amount(str(value))
                if amount is None:
                    raise ToolArgumentsError(f"{name}: not an amount (e.g. '1.000.000 đ')")
                parameters[name] = amount
            elif fmt == FORMAT_DATE and value is not None:
                try:
                    parameters[name] = date.fromisoformat(value)
                except ValueError as exc:
                    raise ToolArgumentsError(f"{name}: expected a date like 2026-09-30") from exc
            else:
                parameters[name] = Decimal(str(value)) if isinstance(value, float) else value
        return parameters
