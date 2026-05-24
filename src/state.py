"""Estado global compartilhado — evita circular imports"""
from src.config import get_settings
from src.core.room import RoomManager
from src.ws.manager import SocketManager

settings = get_settings()
room_manager = RoomManager()
socket_manager = SocketManager(room_manager)
