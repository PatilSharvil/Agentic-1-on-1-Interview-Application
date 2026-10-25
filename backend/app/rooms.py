import random
import string

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Participant, Room, Transcript

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gen_code(n: int = 8) -> str:
    return "".join(random.choice(ALPHABET) for _ in range(n))


async def create_room(db: AsyncSession, host_name: str) -> Room:
    for _ in range(5):
        code = gen_code()
        exists = await db.scalar(select(Room).where(Room.code == code))
        if not exists:
            room = Room(code=code, host_name=host_name)
            db.add(room)
            await db.commit()
            await db.refresh(room)
            return room
    raise RuntimeError("could not generate unique room code")


async def get_room(db: AsyncSession, code: str) -> Room | None:
    return await db.scalar(select(Room).where(Room.code == code.upper()))


async def add_participant(db: AsyncSession, room: Room, display_name: str, role: str = "guest") -> Participant:
    p = Participant(room_id=room.id, display_name=display_name, role=role)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def save_message(db: AsyncSession, room: Room, sender: str, body: str) -> Message:
    m = Message(room_id=room.id, sender=sender, body=body)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def save_transcript(db: AsyncSession, room: Room, speaker: str, text: str, raw_text: str | None = None, start_ms: int = 0, end_ms: int = 0) -> Transcript:
    t = Transcript(room_id=room.id, speaker=speaker, text=text, raw_text=raw_text, start_ms=start_ms, end_ms=end_ms)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def participant_count(db: AsyncSession, room: Room) -> int:
    return await db.scalar(
        select(func.count()).select_from(Participant).where(Participant.room_id == room.id, Participant.left_at.is_(None))
    ) or 0


async def mark_participant_left(db: AsyncSession, room: Room, display_name: str) -> None:
    """Mark the most recent active participant with this name as gone."""
    p = await db.scalar(
        select(Participant)
        .where(
            Participant.room_id == room.id,
            Participant.display_name == display_name,
            Participant.left_at.is_(None),
        )
        .order_by(Participant.joined_at.desc())
    )
    if p:
        from datetime import datetime

        p.left_at = datetime.utcnow()
        await db.commit()


async def mark_participant_row_left(db: AsyncSession, participant_id: str) -> None:
    """Mark one specific participant row as gone.

    On a page reload the reloaded client registers a NEW active row before the
    old socket's cleanup runs; marking by name would retire the fresh row and
    drift the room headcount (and with it, host-role assignment).
    """
    p = await db.get(Participant, participant_id)
    if p and p.left_at is None:
        from datetime import datetime

        p.left_at = datetime.utcnow()
        await db.commit()
