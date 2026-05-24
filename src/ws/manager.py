import asyncio
import time
from typing import Optional

from src.config import get_settings
from src.core.room import RoomManager

settings = get_settings()


class SocketManager:
    def __init__(self, room_manager: RoomManager):
        self.room_manager = room_manager
        self.sio = None
        self.connection_count = 0
        self._sid_to_room: dict = {}

    def attach_sio(self, sio):
        self.sio = sio
        self._register_handlers()

    def _register_handlers(self):
        @self.sio.on("connect")
        async def on_connect(sid, environ):
            self.connection_count += 1
            if settings.DEBUG:
                print(f"[WS] Connect: {sid}")

        @self.sio.on("disconnect")
        async def on_disconnect(sid):
            self.connection_count -= 1
            await self._handle_leave(sid)
            if settings.DEBUG:
                print(f"[WS] Disconnect: {sid}")

        # Frontend emite 'join', não 'join_room'
        @self.sio.on("join")
        async def on_join(sid, data):
            room_id = data.get("room_id", "").upper()
            password = data.get("password")
            public_key = data.get("public_key")

            room = await self.room_manager.get_room(room_id)
            if not room:
                await self.sio.emit("error", {"message": "Sala nao encontrada"}, to=sid)
                return
            if room.is_expired():
                await self.sio.emit("error", {"message": "Sala expirada"}, to=sid)
                return
            if room.password and room.password != password:
                await self.sio.emit("error", {"message": "Senha incorreta"}, to=sid)
                return
            if not room.add_participant(sid, public_key):
                await self.sio.emit("error", {"message": "Sala cheia ou destruida"}, to=sid)
                return

            await self.sio.enter_room(sid, room_id)
            self._sid_to_room[sid] = room_id

            # Frontend espera 'joined', não 'room_joined'
            peers = [
                {"sid": p.sid, "public_key": p.public_key}
                for p in room.participants.values()
                if p.sid != sid
            ]
            await self.sio.emit("joined", {
                "room_id": room_id,
                "peers": peers,
                "forward_secrecy": room.forward_secrecy,
            }, to=sid)

            # Notifica outros peers
            await self.sio.emit("peer_joined", {
                "sid": sid,
                "public_key": public_key,
            }, room=room_id, skip_sid=sid)

            if settings.DEBUG:
                print(f"[WS] {sid} entrou na sala {room_id}")

        # Frontend emite 'leave', não 'leave_room'
        @self.sio.on("leave")
        async def on_leave(sid, data=None):
            await self._handle_leave(sid)

        # Frontend emite 'public_key' e 'key_exchange_complete'
        @self.sio.on("public_key")
        async def on_public_key(sid, data):
            room_id = self._sid_to_room.get(sid)
            if not room_id:
                return
            target_sid = data.get("target_sid")
            public_key = data.get("public_key")
            salt = data.get("salt")
            if target_sid and public_key:
                await self.sio.emit("public_key", {
                    "sid": sid,
                    "public_key": public_key,
                    "salt": salt,
                }, to=target_sid)

        @self.sio.on("key_exchange_complete")
        async def on_key_exchange_complete(sid, data):
            room_id = self._sid_to_room.get(sid)
            if not room_id:
                return
            target_sid = data.get("target_sid")
            public_key = data.get("public_key")
            salt = data.get("salt")
            if target_sid and public_key:
                await self.sio.emit("key_exchange_complete", {
                    "sid": sid,
                    "public_key": public_key,
                    "salt": salt,
                }, to=target_sid)

        # Frontend emite 'message', não 'encrypted_message'
        @self.sio.on("message")
        async def on_message(sid, data):
            room_id = self._sid_to_room.get(sid)
            if not room_id:
                return
            room = await self.room_manager.get_room(room_id)
            if not room or room.destroyed:
                return

            participant = room.participants.get(sid)
            if participant:
                now = time.time()
                if now - participant.last_activity < 0.1:
                    await self.sio.emit("error", {"message": "Rate limit excedido"}, to=sid)
                    return
                participant.last_activity = now

            room.increment_message()
            # Frontend espera 'message'
            await self.sio.emit("message", {
                "from_sid": sid,
                "iv": data.get("iv"),
                "ciphertext": data.get("ciphertext"),
                "timestamp": time.time(),
            }, room=room_id, skip_sid=sid)

            if room.should_rekey():
                room.do_rekey()
                await self.sio.emit("rekey_required", {
                    "reason": "threshold" if room.message_count == 0 else "timeout"
                }, room=room_id)

        @self.sio.on("typing")
        async def on_typing(sid, data):
            room_id = self._sid_to_room.get(sid)
            if not room_id:
                return
            await self.sio.emit("typing", {
                "sid": sid,
            }, room=room_id, skip_sid=sid)

        @self.sio.on("rekey_complete")
        async def on_rekey_complete(sid, data):
            room_id = self._sid_to_room.get(sid)
            if not room_id:
                return
            await self.sio.emit("rekey_complete", {
                "sid": sid,
                "public_key": data.get("public_key"),
            }, room=room_id, skip_sid=sid)

    async def _handle_leave(self, sid):
        room_id = self._sid_to_room.pop(sid, None)
        if not room_id:
            return
        room = await self.room_manager.get_room(room_id)
        if room:
            room.remove_participant(sid)
            await self.sio.leave_room(sid, room_id)
            if room.participants:
                await self.sio.emit("peer_left", {
                    "sid": sid,
                }, room=room_id)
            else:
                await self.room_manager.delete_room(room_id)
                if settings.DEBUG:
                    print(f"[WS] Sala {room_id} destruida (vazia)")
