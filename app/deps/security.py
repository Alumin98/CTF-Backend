# app/deps/security.py
from fastapi import Depends, HTTPException, status

# your project already has this
from app.auth_token import get_current_user

def require_user(user=Depends(get_current_user)):
    """401 if not logged in; returns the user otherwise."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user

def require_admin(user=Depends(require_user)):
    """403 if the logged-in user is not an admin."""
    # accept either role == "admin" OR a boolean flag is_admin
    if getattr(user, "role", None) == "admin" or getattr(user, "is_admin", False):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin only",
    )
