"""Verify recursive generated models and nested CUE constraints."""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from pydantic import ValidationError

import generated as api


@dataclass(frozen=True)
class InvalidQuery:
    sequence: str
    top_k: int


class MockTransport:
    def __init__(self, inbound: api.Inbound) -> None:
        self._inbound = inbound

    async def send(self, message_id: str, message: api.BaseModel) -> None:
        del message_id, message

    async def recv(self, message_id: str) -> api.Inbound:
        del message_id
        return self._inbound

    async def send_close(self) -> None:
        return None

    async def recv_close(self) -> None:
        return None


def query_payload(sequence: str, top_k: int) -> dict[str, object]:
    return {
        "id": "q1",
        "filter.sequence": "root-level",
        "wire/route/path": "root-slash",
        "wire~1name": "tilde",
        "wire/name": "slash",
        "filter": {
            "sequence": sequence,
            "range": {"topK": top_k, "active": True},
        },
        "wire": {"route/path": "nested-slash"},
    }


class NestedObjectModels(unittest.IsolatedAsyncioTestCase):
    async def test_nested_types_and_constraints(self) -> None:
        query = api.Query.model_validate(query_payload("ACGT", 5))
        self.assertIsInstance(query.filter, api.QueryFilter)
        self.assertIsInstance(query.filter.range, api.QueryFilterRange)
        self.assertTrue(query.filter.range.active)
        self.assertIsNone(query.filter.note)
        self.assertEqual(query.filter.sequence, "ACGT")
        self.assertEqual(query.filter_sequence, "root-level")
        self.assertEqual(query.wire.route_path, "nested-slash")
        self.assertEqual(query.wire_route_path, "root-slash")
        self.assertEqual(query.wire_1name, "tilde")
        self.assertEqual(query.wire_name, "slash")
        self.assertIsNone(query.details)

        invalid_queries = [
            InvalidQuery(sequence="ACGX", top_k=5),
            InvalidQuery(sequence="ACGT", top_k=0),
            InvalidQuery(sequence="ACGT", top_k=101),
        ]
        for invalid_query in invalid_queries:
            with self.subTest(
                sequence=invalid_query.sequence,
                top_k=invalid_query.top_k,
            ):
                with self.assertRaises(ValidationError):
                    api.Query.model_validate(
                        query_payload(invalid_query.sequence, invalid_query.top_k)
                    )

    async def test_nested_required_and_unknown_fields(self) -> None:
        missing_required = query_payload("ACGT", 5)
        missing_required["filter"] = {"sequence": "ACGT"}
        with self.assertRaises(ValidationError):
            api.Query.model_validate(missing_required)
        unknown_nested = query_payload("ACGT", 5)
        filter_value = unknown_nested["filter"]
        assert isinstance(filter_value, dict)
        filter_value["note"] = None
        with self.assertRaises(ValidationError):
            api.Query.model_validate(unknown_nested)

    async def test_optional_nested_object_presence_and_null(self) -> None:
        payload = query_payload("ACGT", 5)
        payload["details"] = {"label": "valid"}
        query = api.Query.model_validate(payload)
        self.assertIsInstance(query.details, api.QueryDetails)
        self.assertEqual(query.details.label, "valid")

        invalid_details_cases: list[object] = [None, {"label": ""}]
        for invalid_details in invalid_details_cases:
            with self.subTest(details=invalid_details):
                invalid_payload = query_payload("ACGT", 5)
                invalid_payload["details"] = invalid_details
                with self.assertRaises(ValidationError):
                    api.Query.model_validate(invalid_payload)
        extra_nested = query_payload("ACGT", 5)
        filter_value = extra_nested["filter"]
        assert isinstance(filter_value, dict)
        range_value = filter_value["range"]
        assert isinstance(range_value, dict)
        range_value["unexpected"] = True
        with self.assertRaises(ValidationError):
            api.Query.model_validate(extra_nested)

    async def test_receive_api_rejects_nested_constraint_violation(self) -> None:
        transport = MockTransport(api.InboundMessage("Query", query_payload("ACGX", 5)))
        session = api.ServerReady(transport)
        with self.assertRaises(api.MessageValidationFailure):
            await session.recv_query()

    async def test_send_api_revalidates_nested_constraint(self) -> None:
        query = api.Query.model_construct(
            id="q1",
            filter_sequence="root-level",
            wire_route_path="root-slash",
            wire_1name="tilde",
            wire_name="slash",
            filter=api.QueryFilter.model_construct(
                sequence="ACGX",
                range=api.QueryFilterRange.model_construct(top_k=5, active=True),
            ),
            wire=api.QueryWire.model_construct(route_path="nested-slash"),
            details=None,
        )
        session = api.ClientReady(MockTransport(api.InboundClose()))
        with self.assertRaises(api.MessageValidationFailure):
            await session.send_query(query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
