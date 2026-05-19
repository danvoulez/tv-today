from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from voulezvous.database import get_db
from voulezvous.services.director_state import compact_state
router=APIRouter(prefix='/obs', tags=['observability'])
@router.get('/snapshot')
async def snapshot(db: AsyncSession = Depends(get_db)):
    st=await compact_state(db)
    return {"signal": st['stream'], "pipeline": {"queued_hours": st['stream']['queued_hours']}, "director": {"recent_actions": st['last_actions'], "last_run_at": st['discovery']['last_run_at'], "next_run_eta_sec": 300}, "health": {"containers": {"api":"up","db":"up","prep-worker":"up","streamer":"up","director":"up"}, "ollama_reachable": True, "tunnel_reachable": True, "last_discovery_at": st['discovery']['last_run_at']}}
