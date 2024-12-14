from fastapi import HTTPException, Request
from datetime import datetime, timedelta
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, requests_per_minute: int = 5):
        # Store request timestamps for each IP address
        self.requests = defaultdict(list)
        self.requests_per_minute = requests_per_minute

    def check_rate_limit(self, request: Request):
        # Get the client's IP address
        client_ip = request.client.host
        now = datetime.now()
        
        # Remove timestamps older than 1 minute
        self.requests[client_ip] = [
            timestamp for timestamp in self.requests[client_ip]
            if now - timestamp < timedelta(minutes=1)
        ]
        
        # Check if request limit is exceeded
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later."
            )
        
        # Add current timestamp to requests
        self.requests[client_ip].append(now)