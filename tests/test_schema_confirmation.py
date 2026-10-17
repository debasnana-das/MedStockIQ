
def _base_payload() -> dict:
    return {
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "EXP"},
            {"column_index": 2, "source_column": "QTY+FREE"},
            {"column_index": 3, "source_column": "INTERNAL NOTE"},
        ],
        "mappings": [
            {
                "column_index": 0,
                "source_column": "PRODUCT",
                "action": "map",
                "proposed_canonical_field": "product_name",
                "canonical_field": "product_name",
            },
            {
                "column_index": 1,
                "source_column": "EXP",
                "action": "map",
                "proposed_canonical_field": "expiry_date",
                "canonical_field": "expiry_date",
                "date_format": "MM/YY",
                "date_convention": "month_end",
            },
            {
                "column_index": 2,
                "source_column": "QTY+FREE",
                "action": "map",
                "proposed_canonical_field": "quantity",
                "canonical_field": "quantity",
                "quantity_unit": "pack",
                "transaction_type": "purchase_receipt",
                "transformation_rule": "split_quantity_and_free",
                "additional_canonical_fields": ["free_quantity"],
            },
            {
                "column_index": 3,
                "source_column": "INTERNAL NOTE",
                "action": "ignore",
            },
        ],
    }


def test_schema_confirmation_accepts_explicit_valid_choices(client) -> None:
    response = client.post("/api/v1/schema/confirm", json=_base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["schema_status"] == "confirmed"
    assert body["persistence"] == "stateless_not_saved"
    assert body["summary"] == {
        "profiled_column_count": 4,
        "mapped_column_count": 3,
        "ignored_column_count": 1,
        "corrected_suggestion_count": 0,
    }
    composite = next(item for item in body["mappings"] if item["source_column"] == "QTY+FREE")
    assert composite["additional_canonical_fields"] == ["free_quantity"]
    assert composite["transformation_rule"] == "split_quantity_and_free"


def test_schema_confirmation_marks_user_corrected_mapping(client) -> None:
    payload = _base_payload()
    mapping = payload["mappings"][0]
    mapping["proposed_canonical_field"] = "source_product_code"
    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 200
    product = next(item for item in response.json()["mappings"] if item["source_column"] == "PRODUCT")
    assert product["mapping_status"] == "corrected"
    assert product["mapping_origin"] == "user_corrected"


def test_schema_confirmation_requires_a_decision_for_every_column(client) -> None:
    payload = _base_payload()
    payload["mappings"].pop()
    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 422
    assert "Every profiled column needs exactly one decision" in response.text


def test_schema_confirmation_rejects_conflicting_target_fields(client) -> None:
    payload = {
        "profiled_columns": [
            {"column_index": 0, "source_column": "PRODUCT"},
            {"column_index": 1, "source_column": "ITEM NAME"},
        ],
        "mappings": [
            {
                "column_index": 0,
                "source_column": "PRODUCT",
                "action": "map",
                "canonical_field": "product_name",
            },
            {
                "column_index": 1,
                "source_column": "ITEM NAME",
                "action": "map",
                "canonical_field": "product_name",
            },
        ],
    }

    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 422
    assert "mapped by both" in response.text


def test_schema_confirmation_requires_date_format(client) -> None:
    payload = _base_payload()
    payload["mappings"][1].pop("date_format")
    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 422
    assert "requires an explicit date_format" in response.text


def test_schema_confirmation_requires_quantity_unit(client) -> None:
    payload = _base_payload()
    payload["mappings"][2].pop("quantity_unit")
    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 422
    assert "require quantity_unit" in response.text


def test_schema_confirmation_rejects_unhandled_qty_free_composite(client) -> None:
    payload = _base_payload()
    payload["mappings"][2].pop("transformation_rule")
    response = client.post("/api/v1/schema/confirm", json=payload)

    assert response.status_code == 422
    assert "requires transformation_rule" in response.text


def test_field_catalog_explains_required_metadata(client) -> None:
    response = client.get("/api/v1/schema/fields")

    assert response.status_code == 200
    fields = {item["name"]: item for item in response.json()["fields"]}
    assert "date_format" in fields["expiry_date"]["requires"]
    assert "quantity_unit" in fields["quantity"]["requires"]
    assert "transaction_type" in fields["quantity"]["requires"]
