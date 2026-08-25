import pytest
from app.domain.form_validation import (
    FormValidationError,
    validate_attributes,
    validate_form_schema,
)

SCHEMA = [
    {"name": "nama", "label": "Nama", "type": "text", "required": True},
    {"name": "catatan", "label": "Catatan", "type": "textarea", "required": False},
    {"name": "panjang", "label": "Panjang (m)", "type": "number", "required": False, "min": 0, "max": 1000},
    {"name": "kondisi", "label": "Kondisi", "type": "select", "required": True, "options": ["baik", "rusak"]},
    {"name": "fasilitas", "label": "Fasilitas", "type": "multiselect", "required": False, "options": ["pju", "drainase"]},
    {"name": "tanggal", "label": "Tanggal", "type": "date", "required": False},
    {"name": "aktif", "label": "Aktif", "type": "checkbox", "required": False},
    {"name": "foto", "label": "Foto", "type": "file", "required": False, "extensions": ["jpg", "png"]},
]


class TestValidateFormSchema:
    def test_valid_schema_passes(self):
        validate_form_schema(SCHEMA)

    def test_unknown_field_type_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "x", "label": "X", "type": "slider"}])

    def test_duplicate_names_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([
                {"name": "x", "label": "A", "type": "text"},
                {"name": "x", "label": "B", "type": "text"},
            ])

    def test_select_without_options_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "x", "label": "X", "type": "select"}])

    def test_invalid_name_identifier_rejected(self):
        with pytest.raises(FormValidationError):
            validate_form_schema([{"name": "1 bad name!", "label": "X", "type": "text"}])


class TestValidateAttributes:
    def test_valid_attributes_pass(self):
        validate_attributes(SCHEMA, {
            "nama": "Jl. Sudirman", "panjang": 250.5, "kondisi": "baik",
            "fasilitas": ["pju"], "tanggal": "2026-07-18", "aktif": True,
        })

    def test_missing_required_rejected(self):
        with pytest.raises(FormValidationError) as e:
            validate_attributes(SCHEMA, {"nama": "Jl. X"})
        assert any("kondisi" in msg for msg in e.value.errors)

    def test_required_not_enforced_when_disabled(self):
        validate_attributes(SCHEMA, {}, enforce_required=False)

    def test_select_value_not_in_options_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "hancur"})

    def test_number_out_of_range_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "panjang": -5})

    def test_number_wrong_type_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "panjang": "abc"})

    def test_multiselect_must_be_list_of_options(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "fasilitas": ["wifi"]})

    def test_bad_date_rejected(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "tanggal": "18-07-2026"})

    def test_compact_and_weekdate_iso_forms_rejected(self):
        for bad in ("20260718", "2026-W29-6"):
            with pytest.raises(FormValidationError):
                validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "tanggal": bad})

    def test_checkbox_must_be_bool(self):
        with pytest.raises(FormValidationError):
            validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "aktif": "yes"})

    def test_unknown_attribute_keys_are_kept_silently(self):
        # Schema edits never destroy old values: stale keys are tolerated.
        validate_attributes(SCHEMA, {"nama": "x", "kondisi": "baik", "field_lama": "nilai"})
