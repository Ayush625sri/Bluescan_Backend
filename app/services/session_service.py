from typing import Optional, Dict, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, update
from datetime import datetime
from fastapi import HTTPException, status
import json
import uuid
from loguru import logger
from app.models.user import User
from app.core.security import verify_token

# async def verify_token_ws(db: AsyncSession, token: str, user_id: int) -> Optional[User]:
#     """
#     Verifies a JWT token for WebSocket connections.
#     """
#     email = verify_token(token)
#     if not email:
#         logger.info("email not found")
#         return None
#     logger.info("User email found, returning User")
    
#     result = await db.execute(select(User).where(User.email == email, User.id == user_id))
#     user = result.scalars().first()
#     return user
def verify_token_ws(db: Session, token: str, user_id: int) -> Optional[User]:
    """Verify JWT token for WebSocket connections - SYNC version."""
    try:
        email = verify_token(token)
        if not email:
            logger.info("Token verification failed")
            return None
        
        logger.info(f"Token verified for email: {email}")
        
        # Use synchronous query
        user = db.query(User).filter(User.email == email, User.id == user_id).first()
        return user
        
    except Exception as e:
        logger.error(f"Error in verify_token_ws: {str(e)}")
        return None

async def register_device(db: AsyncSession, user: User, device_data: Dict[str, Any]) -> str:
    """
    Registers a device for the user and returns device ID.
    In a real implementation, you would create a device entry in database.
    """
    from app.models.device import Device
    
    # Create a unique device ID if not provided
    device_id = device_data.get("device_id", str(uuid.uuid4()))
    device_name = device_data.get("device_name", "Unknown Device")
    device_type = device_data.get("device_type", "other")
    
    
    result = await db.execute(
        select(Device).where(
            Device.user_id == user.id,
            Device.device_id == device_id
        )
    )
    existing_device = result.scalars().first()

    
    if existing_device:
        # Update existing device
        existing_device.is_active = True
        existing_device.last_active = datetime.utcnow()
        db.commit()
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
    
    return device_id

# Add these functions to session_service.py

async def create_session_request_ws(request_id: str, from_user_id: int, to_user_id: int) -> None:
    """Create a session request record from WebSocket."""
    async with AsyncSession() as db:
        from app.models.session import SessionRequest
        
        # Create request record
        new_request = SessionRequest(
            request_id=request_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            status="pending"
        )
        
        db.add(new_request)
        await db.commit()

async def update_session_request_ws(
    request_id: str, 
    user_id: int, 
    target_id: int, 
    accepted: bool,
    session_id: Optional[str] = None
) -> None:
    """Update a session request from WebSocket."""
    async with AsyncSession() as db:
        from app.models.session import SessionRequest, ActiveSession
        
        # Find the request
        result = await db.execute(
            select(SessionRequest).where(
                SessionRequest.request_id == request_id,
                SessionRequest.to_user_id == user_id,
                SessionRequest.from_user_id == target_id
            )
        )
        request = result.scalars().first()
        
        if not request:
            logger.error(f"Session request {request_id} not found")
            return
        
        # Update request status
        request.status = "accepted" if accepted else "rejected"
        
        # If accepted and session_id provided, create active session
        if accepted and session_id:
            new_session = ActiveSession(
                session_id=session_id,
                request_id=request_id,
                user1_id=request.from_user_id,
                user2_id=user_id,
                is_active=True
            )
            db.add(new_session)
        
        await db.commit()

async def end_session_ws(session_id: str, user_id: int) -> None:
    """End an active session from WebSocket."""
    async with AsyncSession() as db:
        from app.models.session import ActiveSession
        from sqlalchemy import or_
        
        # Find session
        result = await db.execute(
            select(ActiveSession)
            .where(
                ActiveSession.session_id == session_id,
                or_(
                    ActiveSession.user1_id == user_id,
                    ActiveSession.user2_id == user_id
                ),
                ActiveSession.is_active == True
            )
        )
        session = result.scalars().first()
        
        if not session:
            logger.error(f"Active session {session_id} not found")
            return
        
        # Update session
        session.is_active = False
        session.end_time = datetime.utcnow()
        
        await db.commit()

def create_signaling_data() -> Dict[str, Any]:
    """Create WebRTC signaling configuration with ICE servers."""
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
            {"urls": "stun:stun2.l.google.com:19302"},
            {"urls": "stun:stun3.l.google.com:19302"},
            {"urls": "stun:stun4.l.google.com:19302"},
            # Add TURN servers for production use
            # {
            #     "urls": "turn:your-turn-server.com:3478",
            #     "username": "username",
            #     "credential": "password"
            # }
        ],
        "iceTransportPolicy": "all",
        "sdpSemantics": "unified-plan"
    }

async def get_user_brief(user_id: int) -> Optional[Dict[str, Any]]:
    """Get brief user info for status reporting."""
    async with AsyncSession() as db:
        from app.models.user import User
        
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalars().first()
        
        if not user:
            return None
        
        return {
            "id": user.id,
            "name": user.full_name,
            "email": user.email
        }

async def get_user_sessions(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    """
    Gets all active sessions for a user.
    """
    from app.models.device import Device
    
    # Get all active devices for this user
    result = await db.execute(
        select(Device).where(
            Device.user_id == user_id,
            Device.is_active == True
        )
    )
    devices = result.scalars().all()
    
    return [
        {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "device_type": device.device_type,
            "last_active": device.last_active.isoformat(),
            "is_current": False  # Will be updated by client
        }
        for device in devices
    ]

def create_signaling_data() -> Dict[str, Any]:
    """
    Creates WebRTC signaling data for session establishment.
    """
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
            {"urls": "stun:stun2.l.google.com:19302"},
            {"urls": "stun:stun3.l.google.com:19302"},
            {"urls": "stun:stun4.l.google.com:19302"}
            # Add TURN servers for production
            # {"urls": "turn:your-turn-server.com", "username": "user", "credential": "pass"}
        ]
    }

async def update_device_status(db: AsyncSession, user_id: int, device_id: str, is_active: bool) -> None:
    """
    Updates device status (active/inactive).
    """
    from app.models.device import Device
    
    result = await db.execute(
        select(Device).where(
            Device.user_id == user_id,
            Device.device_id == device_id
        )
    )
    device = result.scalars().first()
    
    if device:
        device.is_active = is_active
        device.last_active = datetime.utcnow()
        db.commit()

async def create_session_request(db: AsyncSession, requester_id: int, target_id: int) -> str:
    """Create a new session request record."""
    from app.models.session import SessionRequest
    from app.models.user import User
    from sqlalchemy import select
    import uuid
    
    # First check if target user exists
    result = await db.execute(select(User).where(User.id == target_id))
    target_user = result.scalars().first()
    
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target user with ID {target_id} not found"
        )
    
    # Generate unique request ID
    request_id = str(uuid.uuid4())
    
    # Create request record
    new_request = SessionRequest(
        request_id=request_id,
        from_user_id=requester_id,
        to_user_id=target_id,
        status="pending"
    )
    
    db.add(new_request)
    await db.commit()
    
    return request_id

async def update_session_request(
    db: AsyncSession, request_id: str, user_id: int, accepted: bool
) -> Dict[str, Any]:
    """Update session request status based on response."""
    from app.models.session import SessionRequest, ActiveSession
    
    # Find the request
    result = await db.execute(
        select(SessionRequest).where(
            SessionRequest.request_id == request_id,
            SessionRequest.to_user_id == user_id
        )
    )
    request = result.scalars().first()
    
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session request not found"
        )
    
    # Update request status
    request.status = "accepted" if accepted else "rejected"
    
    # If accepted, create active session
    session_id = None
    if accepted:
        session_id = str(uuid.uuid4())
        new_session = ActiveSession(
            session_id=session_id,
            request_id=request_id,
            user1_id=request.from_user_id,
            user2_id=user_id,
            is_active=True
        )
        db.add(new_session)
    
    await db.commit()
    
    return {
        "status": "success",
        "accepted": accepted,
        "session_id": session_id,
        "requester_id": request.from_user_id
    }

async def get_active_sessions(db: AsyncSession, user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Get all sessions for a user including pending, active, and ended sessions."""
    from app.models.session import SessionRequest, ActiveSession
    from app.models.user import User
    from sqlalchemy import select, or_, and_
    
    # Get pending requests (as target)
    pending_result = await db.execute(
        select(SessionRequest, User)
        .join(User, User.id == SessionRequest.from_user_id)
        .where(
            SessionRequest.to_user_id == user_id,
            SessionRequest.status == "pending"
        )
    )
    
    pending_requests = []
    for request, user in pending_result:
        pending_requests.append({
            "request_id": request.request_id,
            "from_user": {
                "id": user.id,
                "name": user.full_name,
                "email": user.email
            },
            "status": "pending",
            "created_at": request.created_at.isoformat()
        })
    
    # Debug: Check if there are any active sessions in the database
    all_active_query = await db.execute(
        select(ActiveSession).where(ActiveSession.is_active == True)
    )
    all_active_sessions = all_active_query.scalars().all()
    print(f"Total active sessions in database: {len(all_active_sessions)}")
    for session in all_active_sessions:
        print(f"Session {session.session_id}: user1={session.user1_id}, user2={session.user2_id}")
    
    # Get active sessions for this user with a simpler query
    active_query = await db.execute(
        select(ActiveSession).where(
            or_(
                ActiveSession.user1_id == user_id,
                ActiveSession.user2_id == user_id
            ),
            ActiveSession.is_active == True
        )
    )
    active_session_objects = active_query.scalars().all()
    print(f"Active sessions for user {user_id}: {len(active_session_objects)}")
    
    # Now get partner info for each active session
    active_sessions = []
    for session in active_session_objects:
        # Determine partner ID
        partner_id = session.user1_id if session.user1_id != user_id else session.user2_id
        
        # Get partner details
        partner_query = await db.execute(select(User).where(User.id == partner_id))
        partner = partner_query.scalars().first()
        
        if partner:
            active_sessions.append({
                "session_id": session.session_id,
                "partner": {
                    "id": partner.id,
                    "name": partner.full_name,
                    "email": partner.email
                },
                "start_time": session.start_time.isoformat(),
                "is_active": True,
                "status": "active"
            })
    
    # Get ended sessions with a simpler query too
    ended_query = await db.execute(
        select(ActiveSession).where(
            or_(
                ActiveSession.user1_id == user_id,
                ActiveSession.user2_id == user_id
            ),
            ActiveSession.is_active == False
        ).order_by(ActiveSession.end_time.desc()).limit(10)
    )
    ended_session_objects = ended_query.scalars().all()
    print(f"Ended sessions for user {user_id}: {len(ended_session_objects)}")
    
    # Get partner info for each ended session
    ended_sessions = []
    for session in ended_session_objects:
        # Determine partner ID
        partner_id = session.user1_id if session.user1_id != user_id else session.user2_id
        
        # Get partner details
        partner_query = await db.execute(select(User).where(User.id == partner_id))
        partner = partner_query.scalars().first()
        
        if partner:
            ended_sessions.append({
                "session_id": session.session_id,
                "partner": {
                    "id": partner.id,
                    "name": partner.full_name,
                    "email": partner.email
                },
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat() if session.end_time else None,
                "is_active": False,
                "status": "ended",
                "duration": str((session.end_time - session.start_time).total_seconds()) if session.end_time else None
            })
    
    return {
        "pending_requests": pending_requests,
        "active_sessions": active_sessions,
        "ended_sessions": ended_sessions
    }

async def get_session_by_id(db: AsyncSession, session_id: str, user_id: int) -> Optional[Dict[str, Any]]:
    """Get details of a specific session."""
    from app.models.session import ActiveSession
    from app.models.user import User
    from sqlalchemy.sql import or_
    
    # Find session
    result = await db.execute(
        select(ActiveSession)
        .where(
            ActiveSession.session_id == session_id,
            or_(
                ActiveSession.user1_id == user_id,
                ActiveSession.user2_id == user_id
            )
        )
    )
    session = result.scalars().first()
    
    if not session:
        return None
    
    # Get partner info
    partner_id = session.user1_id if session.user1_id != user_id else session.user2_id
    partner_result = await db.execute(select(User).where(User.id == partner_id))
    partner = partner_result.scalars().first()
    
    return {
        "session_id": session.session_id,
        "request_id": session.request_id,
        "partner": {
            "id": partner.id,
            "name": partner.full_name,
            "email": partner.email
        },
        "start_time": session.start_time.isoformat(),
        "end_time": session.end_time.isoformat() if session.end_time else None,
        "is_active": session.is_active,
        "metadata": json.loads(session.session_data) if session.session_data else {}
    }

async def end_session(db: AsyncSession, session_id: str, user_id: int) -> Dict[str, Any]:
    """End an active session."""
    from app.models.session import ActiveSession
    from sqlalchemy.sql import or_
    
    # Find session
    result = await db.execute(
        select(ActiveSession)
        .where(
            ActiveSession.session_id == session_id,
            or_(
                ActiveSession.user1_id == user_id,
                ActiveSession.user2_id == user_id
            ),
            ActiveSession.is_active == True
        )
    )
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active session not found"
        )
    
    # Update session
    session.is_active = False
    session.end_time = datetime.utcnow()
    
    await db.commit()
    
    # Determine partner ID
    partner_id = session.user1_id if session.user1_id != user_id else session.user2_id
    
    return {
        "status": "success",
        "message": "Session ended successfully",
        "session_id": session_id,
        "partner_id": partner_id
    }

async def store_session_metadata(db: AsyncSession, session_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Store metadata for an active session."""
    from app.models.session import ActiveSession
    
    result = await db.execute(
        select(ActiveSession)
        .where(
            ActiveSession.session_id == session_id,
            ActiveSession.is_active == True
        )
    )
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active session not found"
        )
    
    # Update metadata
    session.session_data = json.dumps(metadata)
    
    await db.commit()
    
    return {
        "status": "success",
        "message": "Session metadata updated",
        "session_id": session_id
    }

async def get_current_user_devices(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    """Get all devices belonging to the current user."""
    try:
        from app.models.device import Device
        from sqlalchemy import select
        
        logger.info(f"Querying devices for user_id: {user_id}")
        
        result = await db.execute(
            select(Device).where(Device.user_id == user_id)
            .order_by(Device.last_active.desc())
        )
        devices = result.scalars().all()
        
        logger.info(f"Query returned {len(devices)} devices")
        
        device_list = []
        for device in devices:
            device_dict = {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "device_type": device.device_type,
                "is_active": device.is_active,
                "last_active": device.last_active.isoformat() if device.last_active else None,
                "created_at": device.created_at.isoformat() if device.created_at else None,
                "is_online": False  # Will be updated by caller
            }
            device_list.append(device_dict)
            logger.info(f"Device: {device_dict}")
        
        return device_list
        
    except Exception as e:
        logger.error(f"Error in get_current_user_devices: {str(e)}")
        raise

def get_online_devices_for_user(user_id: int) -> List[str]:
    """Get list of online device IDs for user from WebSocket connections."""
    try:
        from app.api.v1.endpoints.session import active_connections
        
        logger.info(f"Checking online devices for user {user_id}")
        logger.info(f"Active connections: {list(active_connections.keys())}")
        
        if user_id not in active_connections:
            logger.info(f"User {user_id} not in active connections")
            return []
        
        connections = active_connections[user_id]
        logger.info(f"User {user_id} has {len(connections)} connections")
        
        # For now, return mock device IDs based on connection count
        # In real implementation, you'd track actual device IDs per connection
        device_ids = [f"connection_{i}" for i in range(len(connections))]
        
        logger.info(f"Generated device IDs: {device_ids}")
        return device_ids
        
    except Exception as e:
        logger.error(f"Error in get_online_devices_for_user: {str(e)}")
        return []

async def create_device_session_request(
    db: AsyncSession, 
    user_id: int, 
    target_device_id: str
) -> str:
    """Create session request between user's devices."""
    from app.models.session import SessionRequest
    
    request_id = str(uuid.uuid4())
    
    new_request = SessionRequest(
        request_id=request_id,
        from_user_id=user_id,
        to_user_id=user_id,  # Same user
        status="pending"
    )
    
    db.add(new_request)
    await db.commit()
    
    return request_id


def get_real_online_devices_for_user(user_id: int) -> List[Dict[str, Any]]:
    """Get real online devices with actual device IDs and info."""
    try:
        from app.api.v1.endpoints.session import device_connections
        
        logger.info(f"Getting real online devices for user {user_id}")
        
        if user_id not in device_connections:
            logger.info(f"User {user_id} has no active device connections")
            return []
        
        online_devices = []
        for device_id, connection_info in device_connections[user_id].items():
            device_data = connection_info["device_data"]
            connected_at = connection_info["connected_at"]
            last_ping = connection_info["last_ping"]
            
            online_devices.append({
                "device_id": device_id,
                "device_name": device_data.get("device_name", "Unknown Device"),
                "device_type": device_data.get("device_type", "unknown"),
                "is_online": True,
                "connected_at": connected_at,
                "last_ping": last_ping,
                "connection_quality": "good"  # You can implement real quality checking
            })
        
        logger.info(f"Found {len(online_devices)} real online devices")
        return online_devices
        
    except Exception as e:
        logger.error(f"Error getting real online devices: {str(e)}")
        return []

async def get_current_user_devices_enhanced(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    """Get user devices with real online status and enhanced info."""
    try:
        from app.models.device import Device
        from sqlalchemy import select
        
        logger.info(f"Getting enhanced devices for user_id: {user_id}")
        
        # Get devices from database
        result = await db.execute(
            select(Device).where(Device.user_id == user_id)
            .order_by(Device.last_active.desc())
        )
        devices = result.scalars().all()
        
        logger.info(f"Found {len(devices)} devices in database")
        
        # Get real online devices
        online_devices = get_real_online_devices_for_user(user_id)
        online_device_ids = {d["device_id"] for d in online_devices}
        
        device_list = []
        for device in devices:
            # Find matching online device info
            online_info = next(
                (od for od in online_devices if od["device_id"] == device.device_id), 
                None
            )
            
            device_dict = {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "device_type": device.device_type,
                "is_active": device.is_active,
                "is_online": device.device_id in online_device_ids,
                "last_active": device.last_active.isoformat() if device.last_active else None,
                "created_at": device.created_at.isoformat() if hasattr(device, 'created_at') and device.created_at else None,
                "online_info": online_info if online_info else None
            }
            device_list.append(device_dict)
            logger.info(f"Enhanced device: {device_dict}")
        
        return device_list
        
    except Exception as e:
        logger.error(f"Error in get_current_user_devices_enhanced: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )

async def create_real_session_request(
    db: AsyncSession, 
    user_id: int, 
    from_device_id: str,
    target_device_id: str
) -> str:
    """Create session request between specific devices."""
    try:
        from app.models.session import SessionRequest
        
        # Verify both devices belong to the user
        from_device = await get_device_by_id(db, from_device_id, user_id)
        target_device = await get_device_by_id(db, target_device_id, user_id)
        
        if not from_device or not target_device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or both devices not found"
            )
        
        request_id = str(uuid.uuid4())
        
        new_request = SessionRequest(
            request_id=request_id,
            from_user_id=user_id,
            to_user_id=user_id,  # Same user, different devices
            status="pending"
        )
        
        db.add(new_request)
        await db.commit()
        
        logger.info(f"Created session request {request_id} from {from_device_id} to {target_device_id}")
        
        return request_id
        
    except Exception as e:
        logger.error(f"Error creating real session request: {str(e)}")
        raise

async def get_device_by_id(db: AsyncSession, device_id: str, user_id: int) -> Optional[Dict]:
    """Get device info if it belongs to user."""
    try:
        from app.models.device import Device
        from sqlalchemy import select
        
        result = await db.execute(
            select(Device).where(
                Device.device_id == device_id,
                Device.user_id == user_id
            )
        )
        device = result.scalars().first()
        
        if not device:
            return None
        
        return {
            "device_id": device.device_id,
            "device_name": device.device_name,
            "device_type": device.device_type,
            "user_id": device.user_id,
            "is_active": device.is_active,
            "last_active": device.last_active
        }
        
    except Exception as e:
        logger.error(f"Error getting device by ID: {str(e)}")
        return None

def get_device_connection_info(user_id: int, device_id: str) -> Optional[Dict[str, Any]]:
    """Get real-time connection info for a specific device."""
    try:
        from app.api.v1.endpoints.session import device_connections
        
        if (user_id in device_connections and 
            device_id in device_connections[user_id]):
            return device_connections[user_id][device_id]
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting device connection info: {str(e)}")
        return None

def register_device_sync(db: Session, user: User, device_data: Dict[str, Any]) -> str:
    """Register a device synchronously for WebSocket usage."""
    try:
        from app.models.device import Device
        import uuid
        from datetime import datetime
        
        device_id = device_data.get("device_id", str(uuid.uuid4()))
        device_name = device_data.get("device_name", "Unknown Device")
        device_type = device_data.get("device_type", "other")
        
        logger.info(f"Registering device: {device_id}, {device_name}, {device_type} for user {user.id}")
        
        # Check if device exists
        existing_device = db.query(Device).filter(
            Device.user_id == user.id,
            Device.device_id == device_id
        ).first()
        
        if existing_device:
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
        return str(uuid.uuid4())

def update_device_status_sync(db: Session, user_id: int, device_id: str, is_active: bool) -> None:
    """Update device status synchronously."""
    try:
        from app.models.device import Device
        from datetime import datetime
        
        device = db.query(Device).filter(
            Device.user_id == user_id,
            Device.device_id == device_id
        ).first()
        
        if device:
            device.is_active = is_active
            device.last_active = datetime.utcnow()
            db.commit()
            logger.info(f"Updated device {device_id} status to {is_active}")
        
    except Exception as e:
        logger.error(f"Error updating device status: {str(e)}")
        db.rollback()



