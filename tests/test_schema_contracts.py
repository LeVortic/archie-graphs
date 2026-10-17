import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


ROOT = Path(__file__).parents[1]
SCHEMA_DIR = ROOT / "schemas"


def load_schema(name):
    path = SCHEMA_DIR / name
    return json.loads(path.read_text())


def schema_registry():
    registry = Registry()
    for path in SCHEMA_DIR.glob("*.json"):
        schema = json.loads(path.read_text())
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    return registry


def validate_fixture(schema_name, fixture):
    schema = load_schema(schema_name)
    Draft202012Validator(schema, registry=schema_registry()).validate(json.loads(fixture.read_text()))


def test_valid_extractor_result():
    validate_fixture("extractor-result.schema.json", ROOT / "fixtures/schemas/valid/extractor-result.json")


def test_invalid_extractor_result():
    schema = load_schema("extractor-result.schema.json")
    fixture = ROOT / "fixtures/schemas/invalid/extractor-result-missing-status.json"
    with pytest.raises(ValidationError):
        Draft202012Validator(schema, registry=schema_registry()).validate(json.loads(fixture.read_text()))


@pytest.fixture
def valid_extractor_result():
    return json.loads((ROOT / "fixtures/schemas/valid/extractor-result.json").read_text())


def test_rejects_contract_violations(valid_extractor_result):
    schema = load_schema("extractor-result.schema.json")
    invalid_values = []

    value = deepcopy(valid_extractor_result)
    value["unexpected"] = True
    invalid_values.append(value)

    value = deepcopy(valid_extractor_result)
    value["status"] = "unknown"
    invalid_values.append(value)

    value = deepcopy(valid_extractor_result)
    value["schema_version"] = "archie.extractor-result.v0"
    invalid_values.append(value)

    value = deepcopy(valid_extractor_result)
    value["edges"][0]["source"]["path"] = "../secret.cs"
    invalid_values.append(value)

    validator = Draft202012Validator(schema, registry=schema_registry())
    for value in invalid_values:
        with pytest.raises(ValidationError):
            validator.validate(value)


def test_all_schema_files_are_json_schema_documents():
    for path in SCHEMA_DIR.glob("*.json"):
        schema = json.loads(path.read_text())
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("https://github.com/LeVortic/archie-graphs/schemas/")
