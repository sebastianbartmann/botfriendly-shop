import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()


def create_basic_auth(realm: str = "Admin Area"):
    async def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin authentication is not configured. Set ADMIN_USERNAME and ADMIN_PASSWORD.",
            )
        ok_user = secrets.compare_digest(credentials.username.encode(), username.encode())
        ok_pass = secrets.compare_digest(credentials.password.encode(), password.encode())
        if not (ok_user and ok_pass):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized",
                headers={"WWW-Authenticate": f'Basic realm="{realm}"'},
            )
        return credentials

    return verify_auth


require_admin = create_basic_auth()
