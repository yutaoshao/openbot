from __future__ import annotations

from types import SimpleNamespace

from src.identity.service import IdentityService


class _FakeIdentityRepo:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, str]] = {}
        self.reassign_calls: list[tuple[str, str]] = []

    async def get(
        self,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, str] | None:
        return self.items.get((platform, platform_user_id))

    async def set(
        self,
        *,
        user_id: str,
        platform: str,
        platform_user_id: str,
    ) -> dict[str, str]:
        item = {
            "id": f"{platform}-{platform_user_id}",
            "user_id": user_id,
            "platform": platform,
            "platform_user_id": platform_user_id,
            "created_at": "2026-04-12T00:00:00Z",
            "updated_at": "2026-04-12T00:00:00Z",
        }
        self.items[(platform, platform_user_id)] = item
        return item

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, str]]:
        values = list(self.items.values())
        if user_id is not None:
            values = [item for item in values if item["user_id"] == user_id]
        if platform is not None:
            values = [item for item in values if item["platform"] == platform]
        return values

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        self.reassign_calls.append((source_user_id, target_user_id))


class _FakeReassignRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def reassign_user(
        self,
        source_user_id: str,
        target_user_id: str,
    ) -> None:
        self.calls.append((source_user_id, target_user_id))


async def test_resolve_user_id_creates_identity_for_new_platform_user() -> None:
    identity_repo = _FakeIdentityRepo()
    storage = SimpleNamespace(
        user_identities=identity_repo,
        conversations=_FakeReassignRepo(),
        knowledge=_FakeReassignRepo(),
        preferences=_FakeReassignRepo(),
    )
    service = IdentityService(storage)  # type: ignore[arg-type]

    user_id = await service.resolve_user_id(
        platform="telegram",
        platform_user_id="12345",
    )

    assert user_id
    assert identity_repo.items[("telegram", "12345")]["user_id"] == user_id


async def test_bind_identity_merges_existing_user_scope() -> None:
    identity_repo = _FakeIdentityRepo()
    await identity_repo.set(
        user_id="old-user",
        platform="feishu",
        platform_user_id="ou_1",
    )
    conversations = _FakeReassignRepo()
    knowledge = _FakeReassignRepo()
    preferences = _FakeReassignRepo()
    storage = SimpleNamespace(
        user_identities=identity_repo,
        conversations=conversations,
        knowledge=knowledge,
        preferences=preferences,
    )
    service = IdentityService(storage)  # type: ignore[arg-type]

    bound = await service.bind_identity(
        user_id="new-user",
        platform="feishu",
        platform_user_id="ou_1",
    )

    assert bound["user_id"] == "new-user"
    assert conversations.calls == [("old-user", "new-user")]
    assert knowledge.calls == [("old-user", "new-user")]
    assert preferences.calls == [("old-user", "new-user")]
    assert identity_repo.reassign_calls == [("old-user", "new-user")]
