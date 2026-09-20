"""Зависимости FastAPI: текущий пользователь и разграничение доступа по ролям."""

from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.security import decode_access_token
from app.models.user import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_session)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise credentials_error from None

    user = db.scalar(select(User).where(User.login == payload.get("sub")))
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения операции",
            )
        return user

    return dependency


def forbid_admin_to_student_work(user: User) -> None:
    """Закрывает администратору работы обучающихся и их оценки.

    Два ограничения технического задания сразу: доступ к персональным
    данным «без необходимости» и прямое вмешательство в учебный процесс.
    Проверки «чужая карточка» в обработчиках недостаточно — она отсекает
    только постороннего обучающегося, а администратор с действующим токеном
    проходил бы дальше и мог не только прочитать чужую работу с оценкой,
    но и дописать в неё статус или закрыть её за обучающегося.
    """
    if user.role is Role.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Администратору закрыты работы обучающихся и их оценки",
        )


# Роли разведены строго. Техническое задание ограничивает администратора
# в доступе к персональным данным и во вмешательстве в учебный процесс,
# поэтому кабинет преподавателя ему закрыт, а кабинет администратора —
# закрыт преподавателю.
require_teacher = require_roles(Role.TEACHER)
require_student = require_roles(Role.STUDENT)
require_admin = require_roles(Role.ADMIN)
