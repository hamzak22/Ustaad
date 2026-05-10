from __future__ import annotations

from typing import Any, Iterable, Sequence
from uuid import UUID

import psycopg

from modules.notifications.models import NotificationCreate, NotificationItem
from modules.notifications.manager import manager


async def persist_notification(
    conn: psycopg.AsyncConnection,
    payload: NotificationCreate,
) -> NotificationItem:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO Notifications (
                recipient_id, actor_id, notification_type, title, body,
                entity_type, entity_id, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING
                notification_id,
                recipient_id,
                actor_id,
                notification_type,
                title,
                body,
                entity_type,
                entity_id,
                metadata,
                is_read,
                read_at,
                created_at
            """,
            (
                str(payload.recipient_id),
                str(payload.actor_id) if payload.actor_id else None,
                payload.notification_type,
                payload.title,
                payload.body,
                payload.entity_type,
                str(payload.entity_id) if payload.entity_id else None,
                psycopg.types.json.Jsonb(payload.metadata),
            ),
        )
        row = await cur.fetchone()

    return NotificationItem(**row)


async def broadcast_notification(notification: NotificationItem) -> None:
    await manager.send_personal(
        str(notification.recipient_id),
        {"event": "notification", "data": notification.model_dump(mode="json")},
    )


async def create_notification(
    conn: psycopg.AsyncConnection,
    payload: NotificationCreate,
) -> NotificationItem:
    notification = await persist_notification(conn, payload)
    await broadcast_notification(notification)
    return notification


async def get_recent_notifications(
    conn: psycopg.AsyncConnection,
    recipient_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[NotificationItem]:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT
                notification_id,
                recipient_id,
                actor_id,
                notification_type,
                title,
                body,
                entity_type,
                entity_id,
                metadata,
                is_read,
                read_at,
                created_at
            FROM Notifications
            WHERE recipient_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (str(recipient_id), limit, offset),
        )
        rows = await cur.fetchall()
        return [NotificationItem(**row) for row in rows]


async def count_unread_notifications(conn: psycopg.AsyncConnection, recipient_id: UUID) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) AS unread_count FROM Notifications WHERE recipient_id = %s AND is_read = false",
            (str(recipient_id),),
        )
        row = await cur.fetchone()
        return int(row["unread_count"] if row else 0)


async def mark_notification_read(conn: psycopg.AsyncConnection, notification_id: UUID, recipient_id: UUID) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE Notifications
            SET is_read = true,
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
            WHERE notification_id = %s AND recipient_id = %s
            RETURNING notification_id
            """,
            (str(notification_id), str(recipient_id)),
        )
        return await cur.fetchone() is not None


async def mark_all_notifications_read(conn: psycopg.AsyncConnection, recipient_id: UUID) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE Notifications
            SET is_read = true,
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP)
            WHERE recipient_id = %s AND is_read = false
            RETURNING notification_id
            """,
            (str(recipient_id),),
        )
        rows = await cur.fetchall()
        return len(rows)
