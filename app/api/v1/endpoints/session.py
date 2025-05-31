from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException,  status, File, UploadFile
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import json

from app.database import get_db, get_db_sync
from app.core.deps import get_current_user
from app.models.user import User
from app.services import session_service
from app.services import image_service

from app.models.device import Device
from datetime import datetime
import asyncio
import traceback
import uuid
from loguru import logger

router = APIRouter()

# Dictionary to store active websocket connections
# active_connections: Dict[int, List[WebSocket]] = {}
active_connections: Dict[int, List[WebSocket]] = {}
device_connections: Dict[int, Dict[str, Dict[str, Any]]] = {}  # user_id -> device_id -> connection_info

class DeviceConnection:
    def __init__(self, websocket: WebSocket, device_id: str, device_data: Dict[str, Any]):
        self.websocket = websocket
        self.device_id = device_id
        self.device_name = device_data.get("device_name", "Unknown Device")
        self.device_type = device_data.get("device_type", "unknown")
        self.connected_at = datetime.utcnow()
        self.last_ping = datetime.utcnow()
        self.is_active = True

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    user_id: int,
    token: str,
    db: Session = Depends(get_db_sync)
):
    """Enhanced WebSocket endpoint with real device tracking."""
    try:
        # Verify token and get user
        user = session_service.verify_token_ws(db, token, user_id)
        if not user:
            logger.error("WebSocket authentication failed")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception as e:
        logger.error(f"WebSocket authentication error: {str(e)}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    
    await websocket.accept()
    logger.info(f"WebSocket connection established for user {user_id}")
    
    device_connection = None
    device_id = None
    
    try:
        # Wait for device registration message
        device_info = await websocket.receive_text()
        device_data = json.loads(device_info)
        
        logger.info(f"Received device registration: {device_data}")
        
        # Validate device data
        if not device_data.get("device_id") or not device_data.get("device_name"):
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "device_id and device_name are required"
            }))
            return
        
        device_id = device_data["device_id"]
        
        # Register device in database
        registered_device_id = session_service.register_device_sync(db, user, device_data)
        
        # Create device connection tracking
        device_connection = DeviceConnection(websocket, device_id, device_data)
        
        # Add to tracking dictionaries
        if user_id not in active_connections:
            active_connections[user_id] = []
        active_connections[user_id].append(websocket)
        
        if user_id not in device_connections:
            device_connections[user_id] = {}
        
        # Handle multiple connections from same device
        if device_id in device_connections[user_id]:
            # Close previous connection from same device
            old_connection = device_connections[user_id][device_id]
            try:
                await old_connection["websocket"].close(code=1000, reason="New connection from same device")
            except:
                pass
        
        device_connections[user_id][device_id] = {
            "websocket": websocket,
            "device_data": device_data,
            "connected_at": device_connection.connected_at.isoformat(),
            "last_ping": device_connection.last_ping.isoformat(),
            "is_active": True
        }
        
        logger.info(f"Device {device_id} registered for user {user_id}")
        
        # Send confirmation with real device info
        await websocket.send_text(json.dumps({
            "type": "device_registered",
            "device_id": device_id,
            "status": "success",
            "message": "Device registered successfully",
            "registered_at": device_connection.connected_at.isoformat()
        }))
        
        # Send current devices list to this device
        current_devices = session_service.get_real_online_devices_for_user(user_id)
        await websocket.send_text(json.dumps({
            "type": "devices_list",
            "devices": current_devices
        }))
        
        # Notify other devices of this new device
        await notify_other_devices(user_id, device_id, {
            "type": "device_connected",
            "device_id": device_id,
            "device_name": device_data.get("device_name"),
            "device_type": device_data.get("device_type"),
            "connected_at": device_connection.connected_at.isoformat()
        })
        
        # Main WebSocket loop
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                message_type = message.get("type", "unknown")
                
                logger.debug(f"Received {message_type} from device {device_id} (user {user_id})")
                
                # Update last ping time
                device_connections[user_id][device_id]["last_ping"] = datetime.utcnow().isoformat()
                
                if message_type == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }))
                
                elif message_type == "get_devices":
                    devices = session_service.get_real_online_devices_for_user(user_id)
                    await websocket.send_text(json.dumps({
                        "type": "devices_list",
                        "devices": devices
                    }))
                
                elif message_type == "session_request":
                    await handle_real_session_request(websocket, user, user_id, message, device_id)
                
                elif message_type == "session_response":
                    await handle_real_session_response(websocket, user, user_id, message, device_id)
                
                elif message_type == "webrtc_signal":
                    await handle_real_webrtc_signal(websocket, user, user_id, message, device_id)
                
                elif message_type == "ice_candidate":
                    await handle_real_ice_candidate(websocket, user, user_id, message, device_id)
                
                elif message_type == "session_end":
                    await handle_real_session_end(websocket, user, user_id, message, device_id, db)
                
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Unknown message type: {message_type}"
                    }))
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from device {device_id}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON format"
                }))
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user_id}, device {device_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}, device {device_id}: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        # Cleanup connections
        await cleanup_device_connection(user_id, device_id, websocket, db)

async def cleanup_device_connection(user_id: int, device_id: str, websocket: WebSocket, db: Session):
    """Clean up device connection when WebSocket disconnects."""
    try:
        # Remove from active connections
        if user_id in active_connections and websocket in active_connections[user_id]:
            active_connections[user_id].remove(websocket)
            if not active_connections[user_id]:
                del active_connections[user_id]
        
        # Remove from device connections
        if user_id in device_connections and device_id in device_connections[user_id]:
            del device_connections[user_id][device_id]
            if not device_connections[user_id]:
                del device_connections[user_id]
        
        # Update device status in database
        if device_id:
            session_service.update_device_status_sync(db, user_id, device_id, False)
        
        # Notify other devices
        await notify_other_devices(user_id, device_id, {
            "type": "device_disconnected",
            "device_id": device_id,
            "disconnected_at": datetime.utcnow().isoformat()
        })
        
        logger.info(f"Cleaned up device {device_id} for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

async def notify_other_devices(user_id: int, sender_device_id: str, message: Dict[str, Any]):
    """Send message to all other devices of the same user."""
    if user_id not in device_connections:
        return
    
    for device_id, connection_info in device_connections[user_id].items():
        if device_id != sender_device_id:  # Don't send to sender
            try:
                websocket = connection_info["websocket"]
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to notify device {device_id}: {str(e)}")

async def send_to_specific_device(user_id: int, target_device_id: str, message: Dict[str, Any]):
    """Send message to a specific device."""
    if (user_id in device_connections and 
        target_device_id in device_connections[user_id]):
        try:
            websocket = device_connections[user_id][target_device_id]["websocket"]
            await websocket.send_text(json.dumps(message))
            return True
        except Exception as e:
            logger.error(f"Failed to send to device {target_device_id}: {str(e)}")
    return False

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
   
# @router.post("/request", response_model=Dict[str, Any])
# async def create_session_request(
#     request_data: Dict[str, Any],
#     current_user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db)
# ):
#     """Create a new session request from web app to mobile app."""
#     target_user_id = request_data.get("target_user_id")
    
#     if not target_user_id:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Target user ID is required"
#         )
    
#     try:
#         # Create session request record
#         request_id = await session_service.create_session_request(
#             db, current_user.id, target_user_id
#         )
        
#         # Notify target user via WebSocket if connected
#         if target_user_id in active_connections:
#             notification = {
#                 "type": "session_request",
#                 "from_user_id": current_user.id,
#                 "request_id": request_id,
#                 "user_name": current_user.full_name
#             }
            
#             for connection in active_connections[target_user_id]:
#                 await connection.send_text(json.dumps(notification))
        
#         return {
#             "status": "success",
#             "message": "Session request sent",
#             "request_id": request_id
#         }
#     except HTTPException as e:
#         raise e
#     except Exception as e:
#         # Log the error
#         import traceback
#         print(f"Error in create_session_request: {str(e)}")
#         print(traceback.format_exc())
        
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to create session request: {str(e)}"
#         )

@router.post("/request", response_model=Dict[str, Any])
async def create_session_request(
    request_data: Dict[str, Any],  # Should contain target_device_id
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create session request between user's devices."""
    target_device_id = request_data.get("target_device_id")
    
    if not target_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_device_id is required"
        )
    
    # Verify target device belongs to same user
    device = await session_service.get_device_by_id(db, target_device_id, current_user.id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found or doesn't belong to user"
        )
    
    # Create session request
    request_id = await session_service.create_device_session_request(
        db, current_user.id, target_device_id
    )
    
    # Notify target device via WebSocket
    await notify_device(current_user.id, target_device_id, {
        "type": "session_request",
        "request_id": request_id,
        "from_device_id": request_data.get("from_device_id"),
        "device_name": request_data.get("device_name", "Unknown Device")
    })
    
    return {
        "status": "success",
        "request_id": request_id
    }

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

@router.get("/id/{session_id}", response_model=Dict[str, Any])
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

# @router.get("/devices", response_model=Dict[str, Any])
# async def get_available_devices(
#     current_user: User = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db)
# ):
#     """Get current user's devices for session requests."""
#     try:
#         # Debug: Print user info
#         logger.info(f"Getting devices for user {current_user.id}")
        
#         # Get user's devices from database
#         devices = await session_service.get_current_user_devices(db, current_user.id)
#         logger.info(f"Found {len(devices)} devices in database")
        
#         # Get online status from WebSocket connections
#         online_devices = session_service.get_online_devices_for_user(current_user.id)
#         logger.info(f"Found {len(online_devices)} online devices")
        
#         # Update online status
#         for device in devices:
#             device["is_online"] = device["device_id"] in online_devices
        
#         return {
#             "status": "success",
#             "devices": devices,
#             "total_devices": len(devices),
#             "online_devices": len([d for d in devices if d["is_online"]]),
#             "debug_info": {
#                 "user_id": current_user.id,
#                 "db_devices": len(devices),
#                 "websocket_devices": len(online_devices),
#                 "websocket_device_ids": online_devices
#             }
#         }
        
#     except Exception as e:
#         import traceback
#         logger.error(f"Error in get_available_devices: {str(e)}")
#         logger.error(f"Traceback: {traceback.format_exc()}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"Failed to fetch devices: {str(e)}"
#         )

@router.get("/devices", response_model=Dict[str, Any])
async def get_available_devices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's devices with real online status."""
    try:
        logger.info(f"Getting real devices for user {current_user.id}")
        
        # Get enhanced devices with real online status
        devices = await session_service.get_current_user_devices_enhanced(db, current_user.id)
        
        # Get real-time connection statistics
        online_devices = session_service.get_real_online_devices_for_user(current_user.id)
        
        return {
            "status": "success",
            "devices": devices,
            "total_devices": len(devices),
            "online_devices": len([d for d in devices if d["is_online"]]),
            "real_time_info": {
                "active_connections": len(online_devices),
                "connection_details": online_devices
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error in get_available_devices: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch devices: {str(e)}"
        )

@router.post("/{session_id}/images", response_model=Dict[str, Any])
async def upload_session_image(
    session_id: str,
    file: UploadFile = File(...),
    description: Optional[str] = None,
    latitude: Optional[str] = None,
    longitude: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Upload image captured during session."""
    # Validate session belongs to user
    session = await session_service.get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Upload image
    image_info = await image_service.upload_session_image(
        db, session_id, current_user.id, file, description, latitude, longitude
    )
    
    # Notify other device via WebSocket
    await notify_partner_device(session_id, current_user.id, {
        "type": "image_uploaded",
        "image": image_info
    })
    
    return {"status": "success", "image": image_info}

@router.get("/{session_id}/images", response_model=Dict[str, Any])
async def get_session_images(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all images from session."""
    # Verify session access
    session = await session_service.get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    images = await image_service.get_session_images(db, session_id)
    
    return {
        "status": "success",
        "session_id": session_id,
        "images": images
    }
    
@router.get("/{session_id}/summary", response_model=Dict[str, Any])
async def get_session_summary(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get session summary after ending."""
    session = await session_service.get_session_by_id(db, session_id, current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    summary = await session_service.generate_session_summary(db, session_id)
    
    return {
        "status": "success",
        "summary": summary
    }
    
    
async def notify_device(user_id: int, target_device_id: str, message: Dict):
    """Send notification to specific device."""
    if user_id in device_connections:
        if target_device_id in device_connections[user_id]:
            websocket = device_connections[user_id][target_device_id]["websocket"]
            try:
                await websocket.send_text(json.dumps(message))
                return True
            except:
                return False
    return False
async def notify_partner_device(session_id: str, user_id: int, message: Dict):
    """Notify the other device in the session."""
    # In your case, both devices belong to same user
    # You'd need to track which device is the "other" one in the session
    # This is a placeholder - implement based on your session tracking
    pass

def register_device_sync(db: Session, user: User, device_data: Dict[str, Any]) -> str:
    """Register a device synchronously for WebSocket usage."""
    try:
        
        device_id = device_data.get("device_id", str(uuid.uuid4()))
        device_name = device_data.get("device_name", "Unknown Device")
        device_type = device_data.get("device_type", "other")
        
        logger.info(f"Registering device: {device_id}, {device_name}, {device_type}")
        
        # Check if device exists
        existing_device = db.query(Device).filter(
            Device.user_id == user.id,
            Device.device_id == device_id
        ).first()
        
        if existing_device:
            # Update existing device
            existing_device.is_active = True
            existing_device.last_active = datetime.utcnow()
            db.commit()
            logger.info(f"Updated existing device: {device_id}")
            return device_id
        
        # Create new device
        new_device = Device(
            user_id=user.id,
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            is_active=True
        )
        db.add(new_device)
        db.commit()
        
        logger.info(f"Created new device: {device_id}")
        return device_id
        
    except Exception as e:
        logger.error(f"Error registering device: {str(e)}")
        db.rollback()
        return str(uuid.uuid4())  # Return fallback ID
    
    
async def handle_real_session_request(websocket: WebSocket, user: User, user_id: int, message: Dict, from_device_id: str):
    """Handle session request with real device IDs."""
    target_device_id = message.get("target_device_id")
    
    if not target_device_id:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_device_id is required"
        }))
        return
    
    # Check if target device is online
    if not get_device_connection_info(user_id, target_device_id):
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": f"Target device {target_device_id} is not online"
        }))
        return
    
    request_id = str(uuid.uuid4())
    
    # Send request to target device
    success = await send_to_specific_device(user_id, target_device_id, {
        "type": "session_request",
        "request_id": request_id,
        "from_device_id": from_device_id,
        "from_device_name": message.get("from_device_name", "Unknown Device"),
        "message": message.get("message", ""),
        "timestamp": datetime.utcnow().isoformat()
    })
    
    if success:
        # Store request in database
        asyncio.create_task(session_service.store_session_request_async(
            request_id, user_id, from_device_id, target_device_id
        ))
        
        await websocket.send_text(json.dumps({
            "type": "request_sent",
            "request_id": request_id,
            "target_device_id": target_device_id,
            "status": "sent"
        }))
    else:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Failed to send request to target device"
        }))

async def handle_real_session_response(websocket: WebSocket, user: User, user_id: int, message: Dict, from_device_id: str):
    """Handle session response with real device tracking."""
    request_id = message.get("request_id")
    accepted = message.get("accepted", False)
    target_device_id = message.get("target_device_id")
    
    if not all([request_id, target_device_id]):
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "request_id and target_device_id are required"
        }))
        return
    
    response_data = {
        "type": "session_response",
        "request_id": request_id,
        "from_device_id": from_device_id,
        "accepted": accepted,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if accepted:
        session_id = str(uuid.uuid4())
        response_data.update({
            "session_id": session_id,
            "webrtc_config": session_service.create_signaling_data()
        })
        
        # Store session in database
        asyncio.create_task(session_service.create_device_session_async(
            session_id, request_id, user_id, from_device_id, target_device_id
        ))
    
    # Send response to requesting device
    success = await send_to_specific_device(user_id, target_device_id, response_data)
    
    if success:
        await websocket.send_text(json.dumps({
            "type": "response_sent",
            "request_id": request_id,
            "accepted": accepted,
            "session_id": response_data.get("session_id")
        }))
    else:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Failed to send response to requesting device"
        }))

async def handle_real_webrtc_signal(websocket: WebSocket, user: User, user_id: int, message: Dict, from_device_id: str):
    """Handle WebRTC signaling between real devices."""
    target_device_id = message.get("target_device_id")
    session_id = message.get("session_id")
    signal = message.get("signal")
    signal_type = message.get("signal_type")
    
    if not all([target_device_id, session_id, signal, signal_type]):
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "target_device_id, session_id, signal, and signal_type are required"
        }))
        return
    
    # Forward signal to target device
    signal_message = {
        "type": "webrtc_signal",
        "session_id": session_id,
        "from_device_id": from_device_id,
        "signal": signal,
        "signal_type": signal_type,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    success = await send_to_specific_device(user_id, target_device_id, signal_message)
    
    if success:
        await websocket.send_text(json.dumps({
            "type": "signal_sent",
            "session_id": session_id,
            "signal_type": signal_type
        }))
    else:
        await websocket.send_text(json.dumps({
            "type": "error",
            "error": "Failed to send signal to target device"
        }))

    
    