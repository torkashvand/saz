"""Global WebSocket event bus for broadcasting domain events to all clients."""

import asyncio

from fastapi import WebSocket, WebSocketDisconnect

from saz.domain.events import DomainEvent


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast_event(self, event: DomainEvent) -> None:
        """Broadcast a domain event to all connected clients."""
        if not self.active_connections:
            return

        # Serialize event to JSON
        payload = {
            "type": event.event_type,
            "id": event.aggregate_id,
            "ts": event.timestamp.isoformat(),
            "data": event.data,
        }

        # Broadcast to all connections
        disconnected = []
        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_json(payload)
                except Exception:
                    # Mark for removal if send fails
                    disconnected.append(connection)

        # Clean up disconnected clients
        if disconnected:
            async with self._lock:
                for conn in disconnected:
                    self.active_connections.discard(conn)


# Global connection manager instance
connection_manager = ConnectionManager()


async def broadcast_events(events: list[DomainEvent]) -> None:
    """Broadcast a list of domain events to all connected clients."""
    import logging

    logger = logging.getLogger(__name__)

    if not events:
        return

    logger.info(
        f"Broadcasting {len(events)} event(s) to "
        f"{len(connection_manager.active_connections)} client(s)"
    )
    for event in events:
        logger.debug(f"Broadcasting event: {event.event_type} for {event.aggregate_id}")
        await connection_manager.broadcast_event(event)


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint handler for /ws/events."""
    await connection_manager.connect(websocket)

    try:
        # Send connection acknowledgment
        await websocket.send_json(
            {
                "type": "system.connected",
                "id": "system",
                "ts": "",
                "data": {"message": "Connected to global event stream"},
            }
        )

        # Keep connection alive
        while True:
            try:
                # Wait for client messages (ping, close, etc.)
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                # Echo back as pong
                await websocket.send_json(
                    {"type": "system.pong", "id": "system", "ts": "", "data": {}}
                )
            except TimeoutError:
                # Send keepalive ping every 30 seconds
                await websocket.send_json(
                    {"type": "system.ping", "id": "system", "ts": "", "data": {}}
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await connection_manager.disconnect(websocket)
