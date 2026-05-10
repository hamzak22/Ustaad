from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from database import get_db_connection
from modules.auth.routes import get_current_user_id
from modules.auth.token_generator import ALGORITHM, SECRET_KEY
from modules.notifications.manager import manager
from modules.notifications.models import (
    MarkReadResponse,
    NotificationListResponse,
    NotificationUnreadCountResponse,
    WebSocketHandshake,
)
from modules.notifications.service import (
    count_unread_notifications,
    get_recent_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _decode_ws_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: missing subject")
    return user_id


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    user_id = _decode_ws_token(token)
    await manager.connect(user_id, websocket)

    try:
        async with websocket.app.state.db_pool.connection() as db_conn:
            unread_count = await count_unread_notifications(db_conn, UUID(user_id))
            recent_notifications = await get_recent_notifications(db_conn, UUID(user_id), limit=10, offset=0)

            await websocket.send_json(
                WebSocketHandshake(
                    unread_count=unread_count,
                    recent_notifications=recent_notifications,
                ).model_dump(mode="json")
            )

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
    except Exception:
        manager.disconnect(user_id, websocket)
        await websocket.close(code=1011)


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    recipient_id = UUID(user_id)
    items = await get_recent_notifications(conn, recipient_id, limit=limit, offset=offset)
    unread_count = await count_unread_notifications(conn, recipient_id)

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) AS total_count FROM Notifications WHERE recipient_id = %s",
            (user_id,),
        )
        row = await cur.fetchone()

    return NotificationListResponse(
        items=items,
        total_count=int(row["total_count"] if row else 0),
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=NotificationUnreadCountResponse)
async def unread_count(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    return NotificationUnreadCountResponse(
        unread_count=await count_unread_notifications(conn, UUID(user_id))
    )


@router.post("/{notification_id}/read", response_model=MarkReadResponse)
async def read_notification(
    notification_id: UUID,
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    updated = await mark_notification_read(conn, notification_id, UUID(user_id))
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return MarkReadResponse(message="Notification marked as read")


@router.post("/read-all", response_model=MarkReadResponse)
async def read_all_notifications(
    user_id: str = Depends(get_current_user_id),
    conn: psycopg.AsyncConnection = Depends(get_db_connection),
):
    updated_count = await mark_all_notifications_read(conn, UUID(user_id))
    return MarkReadResponse(message=f"Marked {updated_count} notifications as read")
