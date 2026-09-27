"""Local Markdown personal dossiers, separate from general knowledge."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.memory.personal_profile import PersonalProfile

router = APIRouter(prefix="/api/personal-memory", tags=["personal-memory"])
profile = PersonalProfile()


class DocumentEdit(BaseModel):
    content: str
    revision: str


@router.get("")
def list_documents() -> dict[str, list[str]]:
    return {"documents": profile.documents()}


@router.get("/{name:path}")
def read_document(name: str) -> dict[str, str]:
    try:
        content, revision = profile.read_document(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"name": name, "content": content, "revision": revision}


@router.put("/{name:path}")
async def edit_document(name: str, edit: DocumentEdit) -> dict[str, str]:
    try:
        revision = await profile.edit_document(name, edit.content, edit.revision)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"name": name, "content": edit.content, "revision": revision}
