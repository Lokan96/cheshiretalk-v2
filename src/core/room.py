import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
from src.config import get_settings

settings = get_settings()


@dataclass
class Participant:
    sid: str
    public_key: Optional[str] = None
    joined_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    is_typing: bool = False


@dataclass  
class Room:
    id: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + settings.DEFAULT_ROOM_TTL)
    max_participants: int = settings.MAX_PARTICIPANTS_PER_ROOM
    password: Optional[str] = None
    forward_secrecy: bool = True
    participants: Dict[str, Participant] = field(default_factory=dict)
    message_count: int = 0
    last_rekey: float = field(default_factory=time.time)
    destroyed: bool = False

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def is_full(self) -> bool:
        return len(self.participants) >= self.max_participants

    def add_participant(self, sid: str, public_key: Optional[str] = None) -> bool:
        if self.is_full() or self.destroyed:
            return False
        self.participants[sid] = Participant(sid=sid, public_key=public_key)
        return True

    def remove_participant(self, sid: str) -> bool:
        if sid in self.participants:
            del self.participants[sid]
            return True
        return False

    def should_rekey(self) -> bool:
        if not self.forward_secrecy:
            return False
        if self.message_count >= settings.REKEYING_THRESHOLD:
            return True
        if time.time() - self.last_rekey > settings.REKEYING_TIMEOUT:
            return True
        return False

    def increment_message(self):
        self.message_count += 1

    def do_rekey(self):
        self.message_count = 0
        self.last_rekey = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "max_participants": self.max_participants,
            "participant_count": len(self.participants),
            "forward_secrecy": self.forward_secrecy,
            "ttl_remaining": max(0, int(self.expires_at - time.time())),
        }


class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = asyncio.Lock()

    def _generate_id(self) -> str:
        return secrets.token_urlsafe(4)[:6].upper()

    async def create_room(
        self,
        max_participants: int = 2,
        ttl_seconds: int = settings.DEFAULT_ROOM_TTL,
        password: Optional[str] = None,
        forward_secrecy: bool = True,
    ) -> Optional[Room]:
        async with self._lock:
            if len(self.rooms) >= settings.MAX_ROOMS:
                return None
            for _ in range(10):
                room_id = self._generate_id()
                if room_id not in self.rooms:
                    break
            else:
                return None
            ttl = max(settings.MIN_ROOM_TTL, min(ttl_seconds, settings.MAX_ROOM_TTL))
            room = Room(
                id=room_id,
                expires_at=time.time() + ttl,
                max_participants=min(max_participants, settings.MAX_PARTICIPANTS_PER_ROOM),
                password=password,
                forward_secrecy=forward_secrecy,
            )
            self.rooms[room_id] = room
            return room

    async def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id.upper())

    async def delete_room(self, room_id: str) -> bool:
        async with self._lock:
            room_id = room_id.upper()
            if room_id in self.rooms:
                self.rooms[room_id].destroyed = True
                del self.rooms[room_id]
                return True
            return False

    async def cleanup_loop(self):
        while True:
            await asyncio.sleep(30)
            await self._cleanup()

    async def _cleanup(self):
        async with self._lock:
            expired = [
                rid for rid, room in self.rooms.items()
                if room.is_expired() or room.destroyed
            ]
            for rid in expired:
                del self.rooms[rid]
                if settings.DEBUG:
                    print(f"[CLEANUP] Sala {rid} removida")

    async def shutdown(self):
        async with self._lock:
            self.rooms.clear()
