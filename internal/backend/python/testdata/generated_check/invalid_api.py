"""Invalid client transition that mypy must reject."""

from generated import ClientReady, Result

async def invalid_flow(session: ClientReady, message: Result) -> None:
    await session.send_result(message)
