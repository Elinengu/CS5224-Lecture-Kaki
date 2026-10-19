from typing import Annotated

from fastapi import APIRouter, Depends

from .dependencies import get_current_user
from .schemas import CurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me")
def read_current_user(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    return user
