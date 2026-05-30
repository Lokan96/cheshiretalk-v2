import asyncio
import time
from typing import Optional
from collections import defaultdict

from src.config import get_settings
from src.core.room import RoomManager

settings = get_settings()


class SocketManager:
    def __init__(self, room_manager: RoomManager):
        self.room_manager = room_manager
        self.sio = None
        self.connection_count = 0
        self._sid_to_room: dict = {}
        
        # Rate limiting state
        self.connection_tracker = defaultdict(list)  # ip -> [timestamps]
        self.message_tracker = defaultdict(list)       # sid -> [timestamps]

    def attach_sio(self, sio):
        self.sio = sio
        self._register_handlers()

    def _check_rate_limit_ip(self, ip: str) -> bool:
        """Verifica se o IP excedeu o limite de conexoes."""
        now = time.time()
        window = 60  # 1 minuto
        self.connection_tracker[ip] = [t for t in self.connection_tracker[ip] if now - t < window]
        if len(self.connection_tracker[ip]) >= settings.RATE_LIMIT_CONN_PER_IP:
            return False
        self.connection_tracker[ip].append(now)
        return True

    def _check_rate_limit_msg(self, sid: str) -> bool:
        """Verifica se o peer excedeu o limite de mensagens."""
        now = time.time()
        window = 60  # 1 minuto
        self.message_tracker[sid] = [t for t in self.message_tracker[sid] if now - t < window]
        if len(self.message_tracker[sid]) >= settings.RATE_LIMIT_MSG_PER_MIN:
            return False
        self.message_tracker[sid].append(now)
        return True

    def _register_handlers(self):
        @self.sio.on("connect")
        async def on_connect(sid, environ):
            # CSWSH mitigation — validar header Origin
            origin = environ.get('HTTP_ORIGIN', '')
            if origin and origin not in settings.ALLOWED_ORIGINS:
                print(f"[SECURITY] CSWSH bloqueado: origin={origin} sid={sid}")
                return False
            
            # Rate limit por IP
            client_ip = environ.get('REMOTE_ADDR', 'unknown')
            if not self._check_rate_limit_ip(client_ip):
                print(f"[SECURITY] Rate limit IP: {client_ip} sid={sid}")
                return False
            
            self.connection_count += 1
            if settings.DEBUG:
                print(f"[WS] Connect: {sid} origin={origin or 'null'}")

        @self.sio.on("disconnect")
        async def on_disconnect(sid):
            self.connection_count -= 1
            # Cleanup rate limit trackers
            if sid in self.message_tracker:
                del self.message_tracker[sid]
            await self._handle_leave(sid)
            if settings.DEBUG:
                print(f"[WS] Disconnect: {sid}")

        # Frontend emite 'join', nao 'join_room'
        @self.sio.on("join")
        async def on_join(sid, data):
            room_id = data.get("room_id", "").upper()
            public_key = data.get("public_key")

            room = await self.room_manager.get_room(room_id)
            if not room:
                await self.sio.emit("error", {"message": "Sala nao encontrada"}, to=sid)
                return
            if room.is_expired():
                await self.sio.emit("error", {"message": "Sala expirada"}, to=sid)
                return
            if not room.add_participant(sid, public_key):
                await self.sio.emit("error", {"message": "Sala cheia ou destruida"}, to=sid)
                return

            await self.sio.enter_room(sid, room_id)
            self._sid_to_room[sid] = room_id

            # Notificar peer sobre outros participantes
            participants = room.get_participants()
            peers_info = [{"id": p["sid"], "public_key": p["public_key"]} 
                         for p in participants if p["sid"] != sid]
            
            await self.sio.emit("joined", {
                "room_id": room_id,
                "peers": peers_info,
                "ttl": room.ttl_seconds
            }, to=sid)

            # Notificar outros peers
            await self.sio.emit("peer_joined", {
                "peer_id": sid,
                "public_key": public_key
            }, room=room_id, skip_sid=sid)

        @self.sio.on("leave")
        async def on_leave(sid, data=None):
            await self._handle_leave(sid)

        @self.sio.on("key_exchange")
        async def on_key_exchange(sid, data):
            peer_id = data.get("peer_id")
            public_key = data.get("public_key")
            salt = data.get("salt")
            
            if not all([peer_id, public_key, salt]):
                await self.sio.emit("error", {"message": "Dados de key exchange incompletos"}, to=sid)
                return
            
            await self.sio.emit("key_exchange", {
                "peer_id": sid,
                "public_key": public_key,
                "salt": salt
            }, to=peer_id)

        @self.sio.on("key_exchange_complete")
        async def on_key_exchange_complete(sid, data):
            peer_id = data.get("peer_id")
            if peer_id:
                await self.sio.emit("key_exchange_complete", {"peer_id": sid}, to=peer_id)

        @self.sio.on("encrypted_message")
        async def on_encrypted_message(sid, data):
            # Rate limit de mensagens
            if not self._check_rate_limit_msg(sid):
                await self.sio.emit("error", {"message": "Rate limit excedido"}, to=sid)
                return
            
            room_id = data.get("room_id")
            payload = data.get("payload")
            iv = data.get("iv")
            
            if not all([room_id, payload, iv]):
                await self.sio.emit("error", {"message": "Mensagem invalida"}, to=sid)
                return
            
            await self.sio.emit("encrypted_message", {
                "sender": sid,
                "payload": payload,
                "iv": iv,
                "timestamp": data.get("timestamp")
            }, room=room_id, skip_sid=sid)

        @self.sio.on("rekey_request")
        async def on_rekey_request(sid, data):
            peer_id = data.get("peer_id")
            if peer_id:
                await self.sio.emit("rekey_request", {"peer_id": sid}, to=peer_id)
                print(f"[Crypto] Re-keying: {sid[:8]} <-> {peer_id[:8]}")

        @self.sio.on("typing")
        async def on_typing(sid, data):
            room_id = self._sid_to_room.get(sid)
            if room_id:
                await self.sio.emit("typing", {"peer_id": sid}, room=room_id, skip_sid=sid)

    async def _handle_leave(self, sid):
        room_id = self._sid_to_room.pop(sid, None)
        if room_id:
            room = await self.room_manager.get_room(room_id)
            if room:
                room.remove_participant(sid)
                await self.sio.emit("peer_left", {"peer_id": sid}, room=room_id, skip_sid=sid)
                if room.is_empty():
                    await self.room_manager.delete_room(room_id)


# Instancias globais para compatibilidade
sio = None
socket_app = None

def init_socket_manager(room_manager: RoomManager):
    global sio, socket_app
    import socketio
    sio = socketio.AsyncServer(
        async_mode='asgi',
        cors_allowed_origins=settings.ALLOWED_ORIGINS
    )
    socket_app = socketio.ASGIApp(sio)
    socket_manager = SocketManager(room_manager)
    socket_manager.attach_sio(sio)
    return socket_manager, socket_app
