"""
Authentication middleware for the AI Interviewer System.

Provides optional middleware-based authentication that can be
enabled/disabled via configuration.
"""
import logging
from typing import Optional

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response, JSONResponse

from src.core.config import get_settings
from src.core.auth import decode_token, get_auth_config
from src.core.permissions import get_permissions_for_role
from src.models.auth import AuthenticatedUser, AuthConfig

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware for JWT authentication.
    
    This middleware:
    1. Skips auth for public paths (health, docs, etc.)
    2. Validates JWT from Authorization header
    3. Attaches user info to request.state
    
    Note: For most use cases, using FastAPI's Depends() with
    get_current_user() is preferred. This middleware is useful
    for global auth enforcement.
    """
    
    def __init__(self, app, auth_config: Optional[AuthConfig] = None):
        super().__init__(app)
        self.auth_config = auth_config or get_auth_config()
    
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Check if auth is enabled
        settings = get_settings()
        if not getattr(settings, 'auth_enabled', True):
            return await call_next(request)
        
        # Check if path is public
        if self._is_public_path(request.url.path):
            return await call_next(request)
        
        # Skip WebSocket upgrades — they handle auth via ?token= query param
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        
        # Extract and validate token
        try:
            user = await self._authenticate_request(request)
            if user:
                request.state.user = user
        except HTTPException as e:
            return JSONResponse(
                status_code=e.status_code,
                content={"detail": e.detail},
                headers=e.headers or {},
            )
        
        return await call_next(request)
    
    def _is_public_path(self, path: str) -> bool:
        """Check if the path is public (doesn't require auth)."""
        # Normalize path
        path = path.rstrip("/")
        
        for public_path in self.auth_config.public_paths:
            public_path = public_path.rstrip("/")
            # Exact match or prefix match
            if path == public_path or path.startswith(public_path + "/"):
                return True
        
        return False
    
    async def _authenticate_request(self, request: Request) -> Optional[AuthenticatedUser]:
        """Extract and validate JWT from request."""
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Extract token from "Bearer <token>"
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format. Use: Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        token = parts[1]
        
        # Decode and validate token
        token_payload = decode_token(token, self.auth_config)
        
        # Get effective permissions
        if token_payload.permissions:
            effective_permissions = token_payload.permissions
        else:
            effective_permissions = get_permissions_for_role(token_payload.role)
        
        return AuthenticatedUser(
            user_id=token_payload.sub,
            role=token_payload.role,
            permissions=effective_permissions,
            session_id=token_payload.session_id,
            name=token_payload.name,
            email=token_payload.email,
            token_exp=token_payload.exp,
            token_iss=token_payload.iss,
        )


def get_user_from_request(request: Request) -> Optional[AuthenticatedUser]:
    """
    Helper to get authenticated user from request state.
    
    Use this in route handlers when using middleware-based auth:
    
        @app.get("/protected")
        async def protected_route(request: Request):
            user = get_user_from_request(request)
            if not user:
                raise HTTPException(status_code=401)
            return {"user_id": user.user_id}
    """
    return getattr(request.state, "user", None)


def require_auth_middleware(request: Request) -> AuthenticatedUser:
    """
    Dependency that requires user to be authenticated via middleware.
    
    Use when AuthMiddleware is enabled:
    
        @app.get("/protected")
        async def protected_route(user: AuthenticatedUser = Depends(require_auth_middleware)):
            return {"user_id": user.user_id}
    """
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
