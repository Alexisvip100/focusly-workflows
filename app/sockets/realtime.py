# pyrefly: ignore [missing-import]
import socketio
import urllib.parse
from typing import Any

# Create async socketio server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=[
        'https://focusly-front-psi.vercel.app',
        'http://localhost:5173',
        'http://localhost:3000'
    ]
)

# Create socketio app
socket_app = socketio.ASGIApp(sio, socketio_path='socket.io')

@sio.event(namespace='/realtime')
async def connect(sid, environ, auth=None):
    query_string = environ.get('QUERY_STRING', '')
    query_params = urllib.parse.parse_qs(query_string)
    user_id_list = query_params.get('userId')
    user_id = user_id_list[0] if user_id_list else None
    
    if user_id:
        await sio.enter_room(sid, f"user_{user_id}", namespace='/realtime')

@sio.event(namespace='/realtime')
async def disconnect(sid):
    pass

class RealTimeGateway:
    def __init__(self):
        self.sio = sio

    async def emitScheduleUpdate(self, user_id: str, data: Any):
        room_name = f"user_{user_id}"
        await self.sio.emit('schedule_updated', data, room=room_name, namespace='/realtime')

# Singleton instance
realtime_gateway = RealTimeGateway()
