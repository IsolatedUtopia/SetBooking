from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
TokenDep = Annotated[str, Depends(oauth2_scheme)]


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效或已过期的凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(token: TokenDep, session: SessionDep) -> User:
    try:
        user_id = decode_access_token(token)
    except jwt.InvalidTokenError:
        raise _credentials_exception() from None

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_exception()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]