import asyncio, json, os
from datetime import datetime, timezone
import httpx, structlog
from sqlalchemy.ext.asyncio import AsyncSession
from voulezvous.config import settings
from voulezvous.database import async_session
from voulezvous.models.tables import DirectorAction, DirectorRun
from voulezvous.services.director_state import compact_state
from voulezvous.services.director_tools import TOOLS
logger=structlog.get_logger()
PROMPT_TEMPLATE="""You are the director of voulezvous.tv. You operate by emitting JSON actions only.\n\nState:\n{state_json}\n\nAvailable verbs and their args:\n{tool_grammar}\n\nRules:\n- Output ONLY valid JSON: {\"actions\": [{\"verb\": \"...\", \"args\": {...}, \"why\": \"<15 words\"}]}\n- Maximum 5 actions per response.\n- If everything is fine and queued_hours > 4, return {\"actions\": []}.\n- If queued_hours < 4 and there are approved videos: generate_plan.\n- If candidates.approved_unpromoted > 0: promote_candidate (up to 3).\n- If discovery.last_run_at > 6h ago: run_discovery.\n- If an asset has avg_health_score < 0.3 over 5+ plays: block_asset.\n\nRespond now with JSON only.\n"""
async def call_ollama(state):
    prompt=PROMPT_TEMPLATE.format(state_json=json.dumps(state), tool_grammar=','.join(TOOLS.keys()))
    async with httpx.AsyncClient(timeout=60) as c:
        r=await c.post(f"{settings.local_llm_url}/api/generate", json={"model":settings.ollama_model,"prompt":prompt,"stream":False,"format":"json","options":{"temperature":0.3,"num_predict":600}})
    txt=r.json().get('response','{"actions":[]}')
    try:return json.loads(txt)
    except Exception:return {"actions":[]}
async def execute_action(db, run, idx, action):
    a=DirectorAction(run_id=run.id, sequence_index=idx, verb=action.get('verb',''), args=action.get('args',{}), why=action.get('why'), status='pending')
    db.add(a); await db.flush()
    fn=TOOLS.get(a.verb)
    if not fn: a.status='rejected'; a.error='unknown verb'; return
    try:
        a.result=await fn(db, **a.args); a.status='executed'; a.executed_at=datetime.now(timezone.utc)
    except Exception as e:
        a.status='failed'; a.error=str(e)
async def director_tick(db: AsyncSession):
    state=await compact_state(db); run=DirectorRun(started_at=datetime.now(timezone.utc), state_snapshot=state, llm_response={}); db.add(run); await db.flush()
    resp=await call_ollama(state); run.llm_response=resp
    for idx,action in enumerate(resp.get('actions',[])[:5]): await execute_action(db, run, idx, action)
    run.finished_at=datetime.now(timezone.utc); run.action_count=len(resp.get('actions',[])[:5]); await db.commit(); return run
async def run_director_loop():
    while True:
        try:
            async with async_session() as db: await director_tick(db)
        except Exception as e: logger.error('director_tick_failed', error=str(e))
        await asyncio.sleep(int(os.environ.get('DIRECTOR_INTERVAL_SEC','300')))
