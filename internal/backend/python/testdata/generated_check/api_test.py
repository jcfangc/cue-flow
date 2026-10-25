"""Runtime checks for the generated Python protocol API."""

from __future__ import annotations

import unittest

from pydantic import BaseModel, ValidationError

import generated as api
import reserved_generated as reserved


class MockTransport:
    def __init__(self, inbound: api.Inbound) -> None:
        self.inbound = inbound
        self.sent_id: str | None = None
        self.sent_message: BaseModel | None = None

    async def send(self, message_id: str, message: BaseModel) -> None:
        self.sent_id = message_id
        self.sent_message = message

    async def recv(self, message_id: str) -> api.Inbound:
        return self.inbound

    async def send_close(self) -> None:
        return None

    async def recv_close(self) -> None:
        return None


class GeneratedAPI(unittest.IsolatedAsyncioTestCase):
    async def receive_query(self, payload: object, message_id: str = "Query") -> object:
        transport = MockTransport(api.InboundMessage(message_id, payload))
        return await api.ServerReady(transport).recv_query()

    async def test_server_validates_and_transitions(self) -> None:
        result = await self.receive_query({"id": "q1", "sequence": "ACGT", "topK": 5})
        self.assertIsInstance(result, api.Received)
        self.assertEqual(result.message.id, "q1")
        self.assertIsInstance(result.session, api.ServerWaiting)

    async def test_server_rejects_cue_constraint_violations(self) -> None:
        payloads: list[object] = [
            {"id": "q1", "sequence": "ACGX", "topK": 5},
            {"id": "", "sequence": "ACGT", "topK": 5},
            {"id": "q1", "sequence": "ACGT", "topK": 0},
            {"id": "q1", "sequence": "ACGT", "topK": 101},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                await self.assert_query_rejected(payload)

    async def assert_query_rejected(self, payload: object) -> None:
        with self.assertRaises(api.MessageValidationFailure):
            await self.receive_query(payload)

    async def test_integer_boundaries_are_accepted(self) -> None:
        for top_k in [1, 100]:
            with self.subTest(top_k=top_k):
                result = await self.receive_query(
                    {"id": "q1", "sequence": "ACGT", "topK": top_k}
                )
                self.assertIsInstance(result, api.Received)

    async def test_unknown_message_id_is_not_a_transition(self) -> None:
        with self.assertRaises(api.UnexpectedMessage):
            await self.receive_query(
                {"id": "q1", "sequence": "ACGT", "topK": 5}, "Unknown"
            )

    async def test_strict_types_and_optional_field_semantics(self) -> None:
        valid = api.Query.model_validate(
            {"id": "q1", "sequence": "ACGT", "topK": 5}
        )
        self.assertIsNone(valid.note)
        for top_k in [True, "5"]:
            with self.subTest(top_k=top_k):
                self.assert_query_payload_rejected(top_k)
        with self.assertRaises(ValidationError):
            api.Query.model_validate(
                {"id": "q1", "sequence": "ACGT", "topK": 5, "note": None}
            )
        with self.assertRaises(ValidationError):
            api.Query.model_validate(
                {"id": "q1", "sequence": "ACGT", "top_k": 5}
            )

    async def test_pydantic_reserved_field_maps_to_safe_name(self) -> None:
        message = reserved.Ping.model_validate({"modelCopy": "payload"})
        self.assertEqual(message.cue_model_copy, "payload")

    def assert_query_payload_rejected(self, top_k: object) -> None:
        with self.assertRaises(ValidationError):
            api.Query.model_validate(
                {"id": "q1", "sequence": "ACGT", "topK": top_k}
            )

    async def test_client_send_returns_dual_state(self) -> None:
        transport = MockTransport(api.InboundClose())
        session = api.ClientReady(transport)
        query = api.Query.model_validate(
            {"id": "q1", "sequence": "ACGT", "topK": 5}
        )
        following = await session.send_query(query)
        self.assertIsInstance(following, api.ClientWaiting)
        self.assertEqual(transport.sent_id, "Query")
        self.assertEqual(transport.sent_message, query)

    async def test_transition_consumes_previous_session(self) -> None:
        session = api.ClientReady(MockTransport(api.InboundClose()))
        await session.close()
        with self.assertRaises(api.ProtocolError):
            await session.send_query(
                api.Query.model_validate(
                    {"id": "q1", "sequence": "ACGT", "topK": 5}
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
