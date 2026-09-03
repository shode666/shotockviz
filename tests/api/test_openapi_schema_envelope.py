"""bd:deps-2026-09 iter1 re-verify (CHRIS-06 follow-up).

Chris's original review (CHRIS-06) found the OpenAPI schema served at
/openapi.json didn't reflect the actual runtime {data, meta} envelope
shape (response_model-driven schema generation happens before the
ASGI-layer route_class wrapping). Dave's fix (c2e2e40) added
`install_envelope_openapi()` in schemas/envelope.py, which overrides
`app.openapi()` to post-process the generated schema.

No test previously asserted on the OpenAPI document's shape directly
(only runtime response bodies were tested) - this file closes that
gap, and was used as the mutation-kill target for CHRIS-06 in the
iter1 re-verify (see 14-chris-review.md).
"""
from fastapi.testclient import TestClient

from main import app


class TestOpenAPIEnvelopeSchema:
    """Given the generated OpenAPI document, 2xx JSON responses on
    enveloped routes should show the wrapped {data, meta} shape, and
    error responses should reference ErrorEnvelope, not the raw
    per-route response_model / FastAPI-default HTTPValidationError."""

    def test_2xx_json_response_schema_is_wrapped_with_data_and_meta(self):
        # Given a client
        with TestClient(app) as client:
            # When fetching the OpenAPI document
            resp = client.get("/openapi.json")
            schema = resp.json()
            quote_get = schema["paths"]["/api/v1/stocks/{symbol}/quote"]["get"]
            body_schema = quote_get["responses"]["200"]["content"]["application/json"]["schema"]

        # Then the 200 response schema is the {data, meta} envelope, not
        # the route's raw response_model
        assert body_schema.get("required") == ["data", "meta"]
        assert "data" in body_schema.get("properties", {})
        assert body_schema["properties"]["meta"]["$ref"] == "#/components/schemas/ResponseMeta"

    def test_422_response_schema_is_error_envelope_not_default_validation_error(self):
        # Given a client
        with TestClient(app) as client:
            # When fetching the OpenAPI document
            resp = client.get("/openapi.json")
            schema = resp.json()
            quote_get = schema["paths"]["/api/v1/stocks/{symbol}/quote"]["get"]
            error_schema = quote_get["responses"]["422"]["content"]["application/json"]["schema"]

        # Then the error response references ErrorEnvelope
        assert error_schema.get("$ref") == "#/components/schemas/ErrorEnvelope"
