"""History / reading-list API routes (thin handlers; logic in history_service)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.history import HistoryEntry, HistoryList, NotesUpdate
from app.services import history_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=HistoryList)
def list_history(limit: int = 50) -> HistoryList:
    items = history_service.list_recent(limit=limit)
    return HistoryList(count=len(items), items=[{**i, "is_retracted": bool(i["is_retracted"])} for i in items])


@router.get("/{history_id}", response_model=HistoryEntry)
def get_entry(history_id: int) -> HistoryEntry:
    entry = history_service.get(history_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No saved analysis with that id.")
    return HistoryEntry(**entry)


@router.patch("/{history_id}", response_model=dict)
def update_notes(history_id: int, update: NotesUpdate) -> dict:
    if not history_service.set_notes(history_id, update.notes):
        raise HTTPException(status_code=404, detail="No saved analysis with that id.")
    return {"ok": True}


@router.delete("/{history_id}", response_model=dict)
def delete_entry(history_id: int) -> dict:
    if not history_service.delete(history_id):
        raise HTTPException(status_code=404, detail="No saved analysis with that id.")
    return {"ok": True}
