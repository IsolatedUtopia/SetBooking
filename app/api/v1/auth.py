import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_session
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import UserRead, UserRegister

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserRegister,
    session: AsyncSession = Depends(get_session),
) -> User:
    user = User(
        email=data.email,
        student_no=data.student_no,
        name=data.name,
        hashed_password=hash_password(data.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        logger.info("register conflict: %s", exc.orig)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱或学号已被注册",
        ) from exc
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == form.username.lower()))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    if not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    return TokenResponse(access_token=create_access_token(user.id))