from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json

from app.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services import session_service

import asyncio
import traceback
import uuid
from loguru import logger

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
    WebSocket endpoint for real-time session management and WebRTC signaling.
    Authenticates the user and keeps track of active connections.
    """
    # Verify token and get user
    try:
        user = session_service.verify_token_ws(db, token, user_id)
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception as e:
        logger.error(f"WebSocket authentication error: {str(e)}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    # Accept the websocket connection
    await websocket.accept()
    logger.info(f"WebSocket connection established for user {user_id}")
    
    # Add to active connections
    if user_id not in active_connections:
        active_connections[user_id] = []
    active_connections[user_id].append(websocket)
    
    # Register device if needed
    try:
        device_info = await websocket.receive_text()
        device_data = json.loads(device_info)
        device_id = session_service.register_device(db, user, device_data)
        
        # Send initial session data
        session_data = session_service.get_user_sessions(db, user_id)
        await websocket.send_text(json.dumps({"type": "sessions", "data": session_data}))
        
        # Notify other devices of this device
        if user_id in active_connections:
            for conn in active_connections[user_id]:
                if conn != websocket:
                    await conn.send_text(json.dumps({
                        "type": "device_connected",
                        "device_id": device_id,
                        "device_name": device_data.get("device_name", "Unknown Device")
                    }))
        
        # Main WebSocket loop
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            message_type = message.get("type", "unknown")
            
            # Log message type but not full content for privacy
            logger.debug(f"Received {message_type} message from user {user_id}")
            
            # Handle different message types
            if message_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
            elif message_type == "session_request":
                await handle_session_request(websocket, user, user_id, message, device_id)
                
            elif message_type == "session_response":
                await handle_session_response(websocket, user, user_id, message, device_id)
                
            elif message_type == "webrtc_signal":
                await handle_webrtc_signal(websocket, user, user_id, message)
                
            elif message_type == "session_end":
                await handle_session_end(websocket, user, user_id, message, db)
            
            elif message_type == "ice_candidate":
                await handle_ice_candidate(websocket, user, user_id, message)
                
    except WebSocketDisconnect:
        # Remove connection on disconnect
        logger.info(f"WebSocket disconnected for user {user_id}, device {device_id}")
        active_connections[user_id].remove(websocket)
        if not active_connections[user_id]:
            del active_connections[user_id]
        
        # Update device status
        session_service.update_device_status(db, user_id, device_id, False)
        
        # Notify other devices of this device disconnect
        if user_id in active_connections:
            for conn in active_connections[user_id]:
                await conn.send_text(json.dumps({
                    "type": "device_disconnected",
                    "device_id": device_id
                }))
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {str(e)}")
        logger.error(traceback.format_exc())
        if user_id in active_connections and websocket in active_connections[user_id]:
            active_connections[user_id].remove(websocket)
            if not active_connections[user_id]:
                del active_connections[user_id]

@router.get("/webrtc-config", response_model=Dict[str, Any])
async def get_webrtc_config(
    current_user: User = Depends(get_current_user)
):
    """Get WebRTC configuration including ICE servers."""
    config = session_service.create_signaling_data()
    return {
        "status": "success",
        "config": config
    }

@router.get("/status", response_model=Dict[str, Any])
async def get_websocket_status(
    current_user: User = Depends(get_current_user)
):
    """Get current WebSocket connection status."""
    user_id = current_user.id
    
    connected_users = []
    for uid in active_connections.keys():
        if uid != user_id:  # Don't include current user
            # Get user info from database
            user_info = await session_service.get_user_brief(uid)
            if user_info:
                connected_users.append({
                    "user_id": uid,
                    "name": user_info.get("name"),
                    "connections": len(active_connections[uid])
                })
    
    return {
        "status": "success",
        "connected": user_id in active_connections,
        "connection_count": len(active_connections.get(user_id, [])),
        "online_users": connected_users,
        "total_connections": sum(len(conns) for conns in active_connections.values())
    }

async def handle_session_request(websocket: WebSocket, user: User, user_id: int, message: Dict, device_id: str):
    """Handle a session request message."""
    target_user_id = message.get("target_user_id")
    if not target_user_id:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_user_id is required"
        }))
        return
    
    if target_user_id in active_connections:
        # Create a unique request ID
        request_id = str(uuid.uuid4())
        
        # Forward session request to target user
        request_data = {
            "type": "session_request",
            "from_user_id": user_id,
            "request_id": request_id,
            "user_name": user.full_name,
            "device_id": device_id
        }
        
        # Send to all connections of the target user
        for conn in active_connections[target_user_id]:
            await conn.send_text(json.dumps(request_data))
        
        # Acknowledge to the sender
        await websocket.send_text(json.dumps({
            "type": "request_sent",
            "request_id": request_id,
            "target_user_id": target_user_id
        }))
        
        # Store request in database asynchronously
        asyncio.create_task(session_service.create_session_request_ws(
            request_id, user_id, target_user_id))
    else:
        # Target user not online
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Target user is not online"
        }))

async def handle_session_response(websocket: WebSocket, user: User, user_id: int, message: Dict, device_id: str):
    """Handle a session response message."""
    target_user_id = message.get("target_user_id")
    request_id = message.get("request_id")
    accepted = message.get("accepted", False)
    
    if not target_user_id or not request_id:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_user_id and request_id are required"
        }))
        return
    
    if target_user_id in active_connections:
        # Create response data
        response_data = {
            "type": "session_response",
            "from_user_id": user_id,
            "request_id": request_id,
            "accepted": accepted,
            "user_name": user.full_name,
            "device_id": device_id
        }
        
        # If accepted, generate session ID and add ICE servers
        session_id = None
        if accepted:
            session_id = str(uuid.uuid4())
            response_data["session_id"] = session_id
            response_data["signaling"] = session_service.create_signaling_data()
        
        # Send to all connections of the target user
        for conn in active_connections[target_user_id]:
            await conn.send_text(json.dumps(response_data))
        
        # Update request in database asynchronously
        asyncio.create_task(session_service.update_session_request_ws(
            request_id, user_id, target_user_id, accepted, session_id))
    else:
        # Target user not online
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Target user is not online"
        }))

async def handle_webrtc_signal(websocket: WebSocket, user: User, user_id: int, message: Dict):
    """Handle WebRTC signaling (SDP offer/answer)."""
    target_user_id = message.get("target_user_id")
    session_id = message.get("session_id")
    signal = message.get("signal")
    signal_type = message.get("signal_type", "unknown")  # offer, answer
    
    if not target_user_id or not session_id or not signal:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_user_id, session_id and signal are required"
        }))
        return
    
    if target_user_id in active_connections:
        # Forward the signal to target user
        signal_message = {
            "type": "webrtc_signal",
            "from_user_id": user_id,
            "session_id": session_id,
            "signal": signal,
            "signal_type": signal_type
        }
        
        for conn in active_connections[target_user_id]:
            await conn.send_text(json.dumps(signal_message))
    else:
        # Target user not online
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Target user is not online"
        }))

async def handle_ice_candidate(websocket: WebSocket, user: User, user_id: int, message: Dict):
    """Handle ICE candidate exchange."""
    target_user_id = message.get("target_user_id")
    session_id = message.get("session_id")
    candidate = message.get("candidate")
    
    if not target_user_id or not session_id or not candidate:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_user_id, session_id and candidate are required"
        }))
        return
    
    if target_user_id in active_connections:
        # Forward the ICE candidate to target user
        candidate_message = {
            "type": "ice_candidate",
            "from_user_id": user_id,
            "session_id": session_id,
            "candidate": candidate
        }
        
        for conn in active_connections[target_user_id]:
            await conn.send_text(json.dumps(candidate_message))
    else:
        # Target user not online
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Target user is not online"
        }))

async def handle_session_end(websocket: WebSocket, user: User, user_id: int, message: Dict, db: Session):
    """Handle session end request."""
    session_id = message.get("session_id")
    target_user_id = message.get("target_user_id")
    
    if not session_id or not target_user_id:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "session_id and target_user_id are required"
        }))
        return
    
    # Send end notification to target user if online
    if target_user_id in active_connections:
        end_message = {
            "type": "session_ended",
            "session_id": session_id,
            "ended_by": user_id
        }
        
        for conn in active_connections[target_user_id]:
            await conn.send_text(json.dumps(end_message))
    
    # Update session in database asynchronously
    asyncio.create_task(session_service.end_session_ws(session_id, user_id))
    
    # Acknowledge to the sender
    await websocket.send_text(json.dumps({
        "type": "session_end_confirmed",
        "session_id": session_id
    }))
   
@router.post("/request", response_model=Dict[str, Any])
async def create_session_request(
    request_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new session request from web app to mobile app."""
    target_user_id = request_data.get("target_user_id")
    
    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target user ID is required"
        )
    
    try:
        # Create session request record
        request_id = await session_service.create_session_request(
            db, current_user.id, target_user_id
        )
        
        # Notify target user via WebSocket if connected
        if target_user_id in active_connections:
            notification = {
                "type": "session_request",
                "from_user_id": current_user.id,
                "request_id": request_id,
                "user_name": current_user.full_name
            }
            
            for connection in active_connections[target_user_id]:
                await connection.send_text(json.dumps(notification))
        
        return {
            "status": "success",
            "message": "Session request sent",
            "request_id": request_id
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        # Log the error
        import traceback
        print(f"Error in create_session_request: {str(e)}")
        print(traceback.format_exc())
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session request: {str(e)}"
        )
@router.get("/active", response_model=Dict[str, List[Dict[str, Any]]])
async def get_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all sessions for the user, including pending, active, and ended."""
    sessions = await session_service.get_active_sessions(db, current_user.id)
    return sessions

@router.post("/respond", response_model=Dict[str, Any])
async def respond_to_session_request(
    response_data: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Respond to a session request (accept/reject)."""
    request_id = response_data.get("request_id")
    accepted = response_data.get("accepted", False)
    
    # Update session request status
    result = await session_service.update_session_request(
        db, request_id, current_user.id, accepted
    )
    
    if result["requester_id"] in active_connections:
        notification = {
            "type": "session_response",
            "from_user_id": current_user.id,
            "request_id": request_id,
            "accepted": accepted
        }
        
        if accepted:
            # Add signaling data for WebRTC
            notification["signaling"] = session_service.create_signaling_data()
            notification["session_id"] = result["session_id"]
            
        for connection in active_connections[result["requester_id"]]:
            await connection.send_text(json.dumps(notification))
    
    return result

@router.get("/{session_id}", response_model=Dict[str, Any])
async def get_session_status(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific session."""
    session = await session_service.get_session_by_id(db, session_id, current_user.id)
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    return session

@router.post("/{session_id}/end", response_model=Dict[str, Any])
async def end_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """End an active session."""
    result = await session_service.end_session(db, session_id, current_user.id)
    
    # Notify the other user if connected
    if result["partner_id"] in active_connections:
        notification = {
            "type": "session_ended",
            "session_id": session_id,
            "ended_by": current_user.id
        }
        
        for connection in active_connections[result["partner_id"]]:
            await connection.send_text(json.dumps(notification))
    
    return result

@router.post("/{session_id}/metadata", response_model=Dict[str, Any])
async def update_session_metadata(
    session_id: str,
    metadata: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update metadata for an active session."""
    result = await session_service.store_session_metadata(db, session_id, metadata)
    return result