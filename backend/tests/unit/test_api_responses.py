from core.responses import error_payload, is_canonical_payload, success_payload


def test_root_endpoint_uses_canonical_success_envelope() -> None:
    from fastapi.testclient import TestClient
    from main import app

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["status"] == "online"


def test_success_payload_wraps_data_and_optional_meta() -> None:
    payload = success_payload({"public_id": "appt_1"}, meta={"page": 1})

    assert payload == {
        "success": True,
        "data": {"public_id": "appt_1"},
        "meta": {"page": 1},
    }


def test_error_payload_omits_empty_detail() -> None:
    payload = error_payload("NOT_FOUND", "Recurso no encontrado")

    assert payload == {
        "success": False,
        "error_code": "NOT_FOUND",
        "message": "Recurso no encontrado",
    }


def test_canonical_detection_requires_success_key() -> None:
    assert is_canonical_payload({"success": True, "data": []})
    assert is_canonical_payload({"success": False, "error_code": "X", "message": "Y"})
    assert not is_canonical_payload({"data": []})
