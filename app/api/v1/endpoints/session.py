from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List, Dict, Any
import json

from app.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import session_service

router = APIRouter()

# Dictionary to store active websocket connections
active_connections: Dict[int, List[WebSocket]] = {}

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: str,
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time session management.
    Authenticates the user and keeps track of active connections.
    """
    # Verify token and get user
    try:
        user = session_service.verify_token_ws(db, token, user_id)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception as e:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Accept the websocket connection
    await websocket.accept()
    
    # Add to active connections
    if user_id not in active_connections:
        active_connections[user_id] = []
    active_connections[user_id].append(websocket)
    
    # Register device if needed
    device_info = await websocket.receive_text()
    device_data = json.loads(device_info)
    device_id = session_service.register_device(db, user, device_data)
    
    try:
        # Send initial session data
        session_data = session_service.get_user_sessions(db, user_id)
        await websocket.send_text(json.dumps({"type": "sessions", "data": session_data}))
        
        # Main WebSocket loop
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message["type"] == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
            elif message["type"] == "session_request":
                # Process session request
                target_user_id = message["target_user_id"]
                if target_user_id in active_connections:
                    # Forward session request to target user
                    request_data = {
                        "type": "session_request",
                        "from_user_id": user_id,
                        "device_id": device_id
                    }
                    for conn in active_connections[target_user_id]:
                        await conn.send_text(json.dumps(request_data))
            
            elif message["type"] == "session_response":
                # Process session response
                target_user_id = message["target_user_id"]
                accepted = message["accepted"]
                
                if target_user_id in active_connections:
                    # Forward session response
                    response_data = {
                        "type": "session_response",
                        "from_user_id": user_id,
                        "accepted": accepted,
                        "device_id": device_id
                    }
                    
                    if accepted:
                        # Create signaling data
                        signaling_data = session_service.create_signaling_data()
                        response_data["signaling"] = signaling_data
                        
                    for conn in active_connections[target_user_id]:
                        await conn.send_text(json.dumps(response_data))
            
            elif message["type"] == "webrtc_signal":
                # Handle WebRTC signaling
                target_user_id = message["target_user_id"]
                signal_data = message["signal"]
                
                if target_user_id in active_connections:
                    signal_message = {
                        "type": "webrtc_signal",
                        "from_user_id": user_id,
                        "signal": signal_data
                    }
                    for conn in active_connections[target_user_id]:
                        await conn.send_text(json.dumps(signal_message))
                        
    except WebSocketDisconnect:
        # Remove connection on disconnect
        active_connections[user_id].remove(websocket)
        if not active_connections[user_id]:
            del active_connections[user_id]
        
        # Update device status
        session_service.update_device_status(db, user_id, device_id, False)