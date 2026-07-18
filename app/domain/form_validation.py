"""Form Schema validation for survey Projects.

A Form Schema is an ordered list of field dicts:
    {"name": "kondisi", "label": "Kondisi", "type": "select", "required": true,
     "options": ["baik", "rusak"], "min": null, "max": null, "extensions": ["jpg"]}

`name` is the attribute key (identifier), `label` display text.
Unknown attribute keys on stored Features are tolerated (mutable, unversioned
schema — see CONTEXT.md "Form Schema").
"""
import re
from datetime import date

FIELD_TYPES = frozenset(
    {"text", "textarea", "number", "select", "multiselect", "date", "checkbox", "file"}
)
_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_OPTION_TYPES = {"select", "multiselect"}


class FormValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_form_schema(schema: list) -> None:
    errors: list[str] = []
    if not isinstance(schema, list):
        raise FormValidationError(["form_schema must be a list"])
    seen: set[str] = set()
    for i, field in enumerate(schema):
        if not isinstance(field, dict):
            errors.append(f"field #{i} must be an object")
            continue
        name = field.get("name")
        ftype = field.get("type")
        if not name or not isinstance(name, str) or not _NAME_RE.match(name):
            errors.append(f"field #{i}: invalid name {name!r}")
        elif name in seen:
            errors.append(f"duplicate field name {name!r}")
        else:
            seen.add(name)
        if not field.get("label"):
            errors.append(f"field {name!r}: label is required")
        if ftype not in FIELD_TYPES:
            errors.append(f"field {name!r}: unknown type {ftype!r}")
            continue
        if ftype in _OPTION_TYPES:
            options = field.get("options")
            if not isinstance(options, list) or not options:
                errors.append(f"field {name!r}: {ftype} requires non-empty options")
        if ftype == "number":
            for bound in ("min", "max"):
                v = field.get(bound)
                if v is not None and not isinstance(v, (int, float)):
                    errors.append(f"field {name!r}: {bound} must be a number")
    if errors:
        raise FormValidationError(errors)


def _check_value(field: dict, value, errors: list[str]) -> None:
    name, ftype = field["name"], field["type"]
    if ftype in ("text", "textarea"):
        if not isinstance(value, str):
            errors.append(f"{name}: must be a string")
    elif ftype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{name}: must be a number")
            return
        lo, hi = field.get("min"), field.get("max")
        if lo is not None and value < lo:
            errors.append(f"{name}: below minimum {lo}")
        if hi is not None and value > hi:
            errors.append(f"{name}: above maximum {hi}")
    elif ftype == "select":
        if value not in field.get("options", []):
            errors.append(f"{name}: {value!r} not in options")
    elif ftype == "multiselect":
        options = field.get("options", [])
        if not isinstance(value, list) or any(v not in options for v in value):
            errors.append(f"{name}: must be a list of allowed options")
    elif ftype == "date":
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            errors.append(f"{name}: must be an ISO date (YYYY-MM-DD)")
        else:
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"{name}: must be an ISO date (YYYY-MM-DD)")
    elif ftype == "checkbox":
        if not isinstance(value, bool):
            errors.append(f"{name}: must be a boolean")
    elif ftype == "file":
        if not isinstance(value, str):
            errors.append(f"{name}: must be an attachment reference string")


def validate_attributes(schema: list, attributes: dict, *, enforce_required: bool = True) -> None:
    if not isinstance(attributes, dict):
        raise FormValidationError(["attributes must be an object"])
    errors: list[str] = []
    for field in schema:
        name = field["name"]
        value = attributes.get(name)
        if value is None or value == "" or value == []:
            if enforce_required and field.get("required"):
                errors.append(f"{name}: required")
            continue
        _check_value(field, value, errors)
    if errors:
        raise FormValidationError(errors)
