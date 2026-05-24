from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional

from src.state import settings, room_manager

router = APIRouter(tags=["rooms"])


class CreateRoomRequest(BaseModel):
    max_participants: int = Field(default=2, ge=2, le=10)
    ttl_seconds: int = Field(default=600, ge=30, le=86400)
    password: Optional[str] = Field(default=None, max_length=32)
    forward_secrecy: bool = True


class RoomResponse(BaseModel):
    room_id: str
    expires_at: float
    max_participants: int
    forward_secrecy: bool
    ttl_remaining: int
    ws_url: str


class RoomListResponse(BaseModel):
    rooms: list
    total: int


@router.post("/rooms", response_model=RoomResponse, status_code=201)
async def create_room(req: CreateRoomRequest):
    room = await room_manager.create_room(
        max_participants=req.max_participants,
        ttl_seconds=req.ttl_seconds,
        password=req.password,
        forward_secrecy=req.forward_secrecy,
    )
    if not room:
        raise HTTPException(status_code=503, detail="Limite de salas atingido")
    return RoomResponse(
        room_id=room.id,
        expires_at=room.expires_at,
        max_participants=room.max_participants,
        forward_secrecy=room.forward_secrecy,
        ttl_remaining=room.to_dict()["ttl_remaining"],
        ws_url="/ws",
    )


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    room = await room_manager.get_room(room_id)
    if not room or room.is_expired():
        raise HTTPException(status_code=404, detail="Sala nao encontrada ou expirada")
    return room.to_dict()


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(room_id: str):
    success = await room_manager.delete_room(room_id)
    if not success:
        raise HTTPException(status_code=404, detail="Sala nao encontrada")
    return None


@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms(
    active_only: bool = Query(default=True),
    limit: int = Query(default=20, le=100),
):
    rooms = []
    for rid, room in list(room_manager.rooms.items())[:limit]:
        if active_only and (room.is_expired() or room.destroyed):
            continue
        rooms.append(room.to_dict())
    return RoomListResponse(rooms=rooms, total=len(rooms))
