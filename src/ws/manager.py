import socketio
import time
from collections import defaultdict
from src.core.room import RoomManager
from src.config import settings

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=settings.ALLOWED_ORIGINS
)
socket_app = socketio.ASGIApp(sio)
room_manager = RoomManager()

# Rate limiting state
connection_tracker = defaultdict(list)  # ip -> [timestamps]
message_tracker = defaultdict(list)     # sid -> [timestamps]


def check_rate_limit_ip(ip: str) -> bool:
    """Verifica se o IP excedeu o limite de conexões."""
    now = time.time()
    window = 60  # 1 minuto
    connection_tracker[ip] = [t for t in connection_tracker[ip] if now - t < window]
    if len(connection_tracker[ip]) >= settings.RATE_LIMIT_CONN_PER_IP:
        return False
    connection_tracker[ip].append(now)
    return True


def check_rate_limit_msg(sid: str) -> bool:
    """Verifica se o peer excedeu o limite de mensagens."""
    now = time.time()
    window = 60  # 1 minuto
    message_tracker[sid] = [t for t in message_tracker[sid] if now - t < window]
    if len(message_tracker[sid]) >= settings.RATE_LIMIT_MSG_PER_MIN:
        return False
    message_tracker[sid].append(now)
    return True


@sio.on("connect")
async def on_connect(sid, environ):
    # CSWSH mitigation — validar header Origin
    origin = environ.get('HTTP_ORIGIN', '')
    if origin and origin not in settings.ALLOWED_ORIGINS:
        print(f"[SECURITY] CSWSH bloqueado: origin={origin} sid={sid}")
        return False
    
    # Rate limit por IP
    client_ip = environ.get('REMOTE_ADDR', 'unknown')
    if not check_rate_limit_ip(client_ip):
        print(f"[SECURITY] Rate limit IP: {client_ip} sid={sid}")
        return False
    
    print(f"[WS] Conectado: {sid} origin={origin or 'null'}")


@sio.on("disconnect")
async def on_disconnect(sid):
    # Cleanup rate limit trackers
    if sid in message_tracker:
        del message_tracker[sid]
    
    for room_id, room in room_manager.rooms.items():
        if sid in room.peers:
            await room.remove_peer(sid)
            await sio.emit(
                "peer_left",
                {"peer_id": sid},
                room=room_id,
                skip_sid=sid
            )
            break


@sio.on("join")
async def on_join(sid, data):
    room_id = data.get("room_id")
    public_key = data.get("public_key")
    
    if not room_id or not public_key:
        await sio.emit("error", {"message": "Dados obrigatórios ausentes"}, to=sid)
        return
    
    room = room_manager.get_or_create(room_id)
    success = await room.add_peer(sid, public_key)
    
    if not success:
        await sio.emit("error", {"message": "Sala cheia ou expirada"}, to=sid)
        return
    
    await sio.enter_room(sid, room_id)
    
    peers_info = [
        {"id": p.id, "public_key": p.public_key}
        for p in room.peers.values() if p.id != sid
    ]
    
    await sio.emit("joined", {"room_id": room_id, "peers": peers_info}, to=sid)
    
    # Notificar peers existentes
    await sio.emit(
        "peer_joined",
        {"peer_id": sid, "public_key": public_key},
        room=room_id,
        skip_sid=sid
    )


@sio.on("key_exchange")
async def on_key_exchange(sid, data):
    peer_id = data.get("peer_id")
    public_key = data.get("public_key")
    salt = data.get("salt")
    
    if not all([peer_id, public_key, salt]):
        await sio.emit("error", {"message": "Dados de key exchange incompletos"}, to=sid)
        return
    
    await sio.emit("key_exchange", {
        "peer_id": sid,
        "public_key": public_key,
        "salt": salt
    }, to=peer_id)


@sio.on("key_exchange_complete")
async def on_key_exchange_complete(sid, data):
    peer_id = data.get("peer_id")
    if peer_id:
        await sio.emit("key_exchange_complete", {"peer_id": sid}, to=peer_id)


@sio.on("encrypted_message")
async def on_encrypted_message(sid, data):
    # Rate limit de mensagens
    if not check_rate_limit_msg(sid):
        await sio.emit("error", {"message": "Rate limit excedido"}, to=sid)
        return
    
    room_id = data.get("room_id")
    payload = data.get("payload")
    iv = data.get("iv")
    
    if not all([room_id, payload, iv]):
        await sio.emit("error", {"message": "Mensagem inválida"}, to=sid)
        return
    
    await sio.emit("encrypted_message", {
        "sender": sid,
        "payload": payload,
        "iv": iv,
        "timestamp": data.get("timestamp")
    }, room=room_id, skip_sid=sid)


@sio.on("rekey_request")
async def on_rekey_request(sid, data):
    peer_id = data.get("peer_id")
    if peer_id:
        await sio.emit("rekey_request", {"peer_id": sid}, to=peer_id)
        print(f"[Crypto] Re-keying: {sid[:8]} <-> {peer_id[:8]}")


@sio.on("typing")
async def on_typing(sid, data):
    room_id = data.get("room_id")
    if room_id:
        await sio.emit("typing", {"peer_id": sid}, room=room_id, skip_sid=sid)
