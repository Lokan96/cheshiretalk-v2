from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio
import asyncio
import time

from src.state import settings, room_manager, socket_manager
from src.api.rooms import router as rooms_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(room_manager.cleanup_loop())
    yield
    await room_manager.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="src/static"), name="static")
app.include_router(rooms_router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse("src/static/index.html")


@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "timestamp": time.time(),
        "active_rooms": len(room_manager.rooms),
        "active_connections": socket_manager.connection_count,
    }


@app.get("/api/v1/status")
async def status():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "debug": settings.DEBUG,
        "max_rooms": settings.MAX_ROOMS,
        "max_participants": settings.MAX_PARTICIPANTS_PER_ROOM,
        "active_rooms": len(room_manager.rooms),
        "active_connections": socket_manager.connection_count,
        "rooms": [
            {
                "id": rid,
                "participants": len(r.participants),
                "expires_at": r.expires_at,
            }
            for rid, r in room_manager.rooms.items()
        ],
    }


# Socket.IO setup — DEPOIS de todas as rotas do FastAPI
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.CORS_ORIGINS,
    logger=settings.DEBUG,
    engineio_logger=settings.DEBUG,
)

socket_manager.attach_sio(sio)

# Cria o ASGI app que combina Socket.IO + FastAPI
# Isso expõe o WebSocket no /socket.io/ e mantém as rotas HTTP
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)
