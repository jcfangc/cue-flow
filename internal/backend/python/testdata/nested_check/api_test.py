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
        "filter": {
            "sequence": sequence,
            "range": {"topK": top_k, "active": True},
        },
    }


class NestedObjectModels(unittest.IsolatedAsyncioTestCase):
    async def test_nested_types_and_constraints(self) -> None:
        query = api.Query.model_validate(query_payload("ACGT", 5))
        self.assertIsInstance(query.filter, api.QueryFilter)
        self.assertIsInstance(query.filter.range, api.QueryFilterRange)
        self.assertTrue(query.filter.range.active)
        self.assertIsNone(query.filter.note)

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
        with self.assertRaises(ValidationError):
            api.Query.model_validate({"id": "q1", "filter": {"sequence": "ACGT"}})
        with self.assertRaises(ValidationError):
            api.Query.model_validate(
                {
                    "id": "q1",
                    "filter": {
                        "sequence": "ACGT",
                        "note": None,
                        "range": {"topK": 5, "active": True},
                    },
                }
            )
        with self.assertRaises(ValidationError):
            api.Query.model_validate(
                {
                    "id": "q1",
                    "filter": {
                        "sequence": "ACGT",
                        "range": {"topK": 5, "active": True, "unexpected": True},
                    },
                }
            )

    async def test_receive_api_rejects_nested_constraint_violation(self) -> None:
        transport = MockTransport(api.InboundMessage("Query", query_payload("ACGX", 5)))
        session = api.ServerReady(transport)
        with self.assertRaises(api.MessageValidationFailure):
            await session.recv_query()

    async def test_send_api_revalidates_nested_constraint(self) -> None:
        query = api.Query.model_construct(
            id="q1",
            filter=api.QueryFilter.model_construct(
                sequence="ACGX",
                range=api.QueryFilterRange.model_construct(top_k=5, active=True),
            ),
        )
        session = api.ClientReady(MockTransport(api.InboundClose()))
        with self.assertRaises(api.MessageValidationFailure):
            await session.send_query(query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
