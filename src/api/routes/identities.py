"""Identity mapping routes for cross-platform user linking."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request

from src.api.schemas import IdentityBindRequest, IdentityItem

if TYPE_CHECKING:
    from src.identity.service import IdentityService

router = APIRouter(prefix="/api/identities", tags=["identities"])


def _get_identity_service(request: Request) -> IdentityService:
    """Get the identity service from app state or raise 503."""
    service = getattr(request.app.state, "identity_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Identity service is not initialized for API requests.",
        )
    return service


@router.get("", response_model=list[IdentityItem])
async def list_identities(
    request: Request,
    user_id: str | None = Query(default=None, min_length=1),
    platform: str | None = Query(default=None, min_length=1),
) -> list[IdentityItem]:
    """List canonical user identity mappings."""
    service = _get_identity_service(request)
    items = await service.list_identities(user_id=user_id, platform=platform)
    return [IdentityItem(**item) for item in items]


@router.post("/bind", response_model=IdentityItem)
async def bind_identity(
    payload: IdentityBindRequest,
    request: Request,
) -> IdentityItem:
    """Bind a Telegram/Feishu account to a shared internal user id."""
    service = _get_identity_service(request)
    item = await service.bind_identity(
        user_id=payload.user_id,
        platform=payload.platform,
        platform_user_id=payload.platform_user_id,
    )
    return IdentityItem(**item)
