"""Executable validation and scoring contracts for pipeline answer shapes."""

import math
from collections.abc import Mapping
from typing import Any


def _schema_fields(schema: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    fields = {}
    for declared_name, descriptor in schema.items():
        if not isinstance(declared_name, str) or not isinstance(descriptor, str):
            raise AnswerContractError(
                "output_schema must map field names to documented type descriptions"
            )
        answer_name = declared_name.removesuffix("_optional")
        if answer_name in fields:
            raise AnswerContractError(
                f"output_schema declares the answer field {answer_name!r} more than once"
            )
        fields[answer_name] = (declared_name, descriptor)
    return fields


class AnswerContractError(ValueError):
    """An answer does not satisfy the selected template's declared contract."""


SCORERS = {
    "boolean": "exact_boolean",
    "box2d": "box_iou",
    "boxes2d": "detection_set",
    "choice": "choice_id",
    "id_set": "unordered_ids",
    "integer": "exact_integer",
    "label": "declared_label",
    "numeric": "numeric_tolerance",
    "ordered_groups": "ordered_groups",
    "ordered_ids": "ordered_ids",
}


def scorer_for(output_kind):
    """Return a scorer only when this harness has explicit semantics for it."""
    try:
        return SCORERS[output_kind]
    except KeyError as exc:
        raise AnswerContractError(
            f"No deterministic scorer is registered for output_kind={output_kind!r}"
        ) from exc


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _number_array(value, length, field):
    if (not isinstance(value, list) or len(value) != length or
            not all(_finite_number(part) for part in value)):
        raise AnswerContractError(f"{field} must contain {length} finite numbers")


def _identifier_list(value, field, *, unique=False):
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise AnswerContractError(f"{field} must be an array of nonempty IDs")
    if unique and len(set(value)) != len(value):
        raise AnswerContractError(f"{field} must not contain duplicate IDs")


def _validate_field(field, descriptor, value, output_kind):
    if not isinstance(descriptor, str):
        raise AnswerContractError(f"Schema descriptor for {field!r} must be text")
    description = descriptor.casefold()
    key = field.casefold()

    if value is None:
        if "optional" in description or "or null" in description:
            return
        raise AnswerContractError(f"{field} cannot be null")

    if key in {"box", "bbox"}:
        _number_array(value, 4, field)
        if value[0] >= value[2] or value[1] >= value[3]:
            raise AnswerContractError(f"{field} must use increasing xyxy coordinates")
        return
    if key == "point":
        _number_array(value, 2, field)
        return
    if key == "vector":
        _number_array(value, 3, field)
        return
    if key in {"value", "degrees", "pitch_deg", "roll_deg", "cost", "confidence"} and "boolean" in description:
        if type(value) is not bool:
            raise AnswerContractError(f"{field} must be boolean")
        return
    if key in {"value", "degrees", "pitch_deg", "roll_deg", "cost", "confidence"}:
        expected_integer = "integer" in description or output_kind == "integer"
        if expected_integer:
            if type(value) is not int or ("nonnegative" in description and value < 0):
                raise AnswerContractError(f"{field} must be a valid integer")
        elif not _finite_number(value):
            raise AnswerContractError(f"{field} must be a finite number")
        return
    if key in {"sequence", "ids", "changed_cells"}:
        _identifier_list(value, field, unique=key != "sequence")
        return
    if key == "groups":
        if not isinstance(value, list):
            raise AnswerContractError("groups must be an array of ID arrays")
        flattened = []
        for group in value:
            _identifier_list(group, "group", unique=True)
            flattened.extend(group)
        if len(set(flattened)) != len(flattened):
            raise AnswerContractError("An ID cannot appear in more than one group")
        return
    if key == "detections":
        if not isinstance(value, list):
            raise AnswerContractError("detections must be an array")
        for detection in value:
            if (not isinstance(detection, dict) or
                    not isinstance(detection.get("class"), str) or
                    not detection["class"].strip()):
                raise AnswerContractError("Each detection needs a nonempty class")
            _validate_field("box", "[xmin,ymin,xmax,ymax]", detection.get("box"), output_kind)
            if "confidence" in detection and not _finite_number(detection["confidence"]):
                raise AnswerContractError("Detection confidence must be finite")
        return
    if key in {"unit", "frame", "label", "choice_id", "text", "action", "region"}:
        if key == "choice_id" and output_kind == "choice" and isinstance(value, list):
            _identifier_list(value, field, unique=True)
        elif not isinstance(value, str) or not value.strip():
            raise AnswerContractError(f"{field} must be nonempty text")
        return
    if key in {"actions", "objects", "path", "grid", "matches", "labels", "map", "answer", "evidence"}:
        if not isinstance(value, (dict, list)):
            raise AnswerContractError(f"{field} must be structured data")
        return

    if "boolean" in description:
        if type(value) is not bool:
            raise AnswerContractError(f"{field} must be boolean")
        return
    if "integer" in description:
        if type(value) is not int:
            raise AnswerContractError(f"{field} must be an integer")
        return
    if "number" in description or "degrees" in description:
        if not _finite_number(value):
            raise AnswerContractError(f"{field} must be a finite number")
        return
    if any(token in description for token in ("array", "list", "sequence", "set", "indices")):
        if not isinstance(value, list):
            raise AnswerContractError(f"{field} must be an array")
        return
    if any(token in description for token in ("map", "object", " -> ", "dictionary")):
        if not isinstance(value, dict):
            raise AnswerContractError(f"{field} must be an object")
        return
    if any(token in description for token in ("label", "text", "id", "string")):
        if not isinstance(value, str) or not value.strip():
            raise AnswerContractError(f"{field} must be nonempty text")
        return

    raise AnswerContractError(
        f"No runtime validator is registered for schema field {field!r}: {descriptor!r}"
    )


def validate_answer(template_or_contract: Mapping[str, Any], answer: Any) -> None:
    """Validate the exact object fields and primitive shapes declared by a template."""
    output_kind = template_or_contract.get("output_kind")
    schema = template_or_contract.get("output_schema")
    if not isinstance(output_kind, str) or not output_kind:
        raise AnswerContractError("Template must declare output_kind")
    if not isinstance(schema, dict) or not schema:
        raise AnswerContractError("Template must declare a nonempty output_schema object")
    if not isinstance(answer, dict):
        raise AnswerContractError("Answer must be an object matching output_schema")

    fields = _schema_fields(schema)
    required = {
        answer_name
        for answer_name, (declared_name, descriptor) in fields.items()
        if not declared_name.endswith("_optional") and "optional" not in descriptor.casefold()
    }
    missing = required - answer.keys()
    unexpected = answer.keys() - fields.keys()
    if missing:
        raise AnswerContractError(f"Answer is missing required fields: {sorted(missing)}")
    if unexpected:
        raise AnswerContractError(f"Answer has fields outside output_schema: {sorted(unexpected)}")

    for field, value in answer.items():
        _, descriptor = fields[field]
        _validate_field(field, descriptor, value, output_kind)


def validate_contract_declaration(template: Mapping[str, Any]) -> dict[str, Any]:
    """Reject malformed schemas before any answer is accepted or scored."""
    output_kind = template.get("output_kind")
    schema = template.get("output_schema")
    if not isinstance(output_kind, str) or not isinstance(schema, dict) or not schema:
        raise AnswerContractError("Template needs output_kind and a nonempty output_schema")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in schema.items()):
        raise AnswerContractError("output_schema must map field names to documented type descriptions")
    _schema_fields(schema)
    scorer = scorer_for(output_kind)
    return {
        "schema_id": "benchforge.answer-contract/v1",
        "output_kind": output_kind,
        "output_schema": schema,
        "scorer": scorer,
    }
