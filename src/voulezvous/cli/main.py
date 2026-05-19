import asyncio
from datetime import date

import click

from voulezvous.logging_config import setup_logging


@click.group()
def cli():
    """Voulezvous streaming engine CLI."""
    setup_logging()


@cli.command("seed-demo-data")
def seed_demo_data_cmd():
    """Load demo assets into the database."""
    asyncio.run(_seed())


async def _seed():
    from voulezvous.database import async_session
    from voulezvous.services.seed import seed_demo_data

    async with async_session() as db:
        result = await seed_demo_data(db)
        click.echo(f"Seeded: {result}")


@cli.command("api")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def run_api(host: str, port: int):
    """Run the FastAPI server."""
    import uvicorn

    uvicorn.run("voulezvous.api.app:app", host=host, port=port, reload=False)


@cli.command("planner")
@click.option("--date", "plan_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--hours", default=24, type=int)
@click.option("--mix-music", is_flag=True, default=False)
def planner_cmd(plan_date, hours: int, mix_music: bool):
    """Generate a stream plan for a date."""
    d = plan_date.date() if hasattr(plan_date, "date") else plan_date
    asyncio.run(_generate_plan(d, hours, mix_music))


async def _generate_plan(plan_date: date, hours: int, mix_music: bool):
    from voulezvous.database import async_session
    from voulezvous.services.planner import generate_plan

    async with async_session() as db:
        plan = await generate_plan(db, plan_date, hours, mix_music)
        click.echo(f"Plan {plan.id} created for {plan_date} with {len(plan.items)} items")


@cli.command("prep-worker")
@click.option("--once", is_flag=True, default=False, help="Run one cycle then exit")
@click.option("--interval", default=30, type=int, help="Poll interval in seconds")
def prep_worker_cmd(once: bool, interval: int):
    """Run the preparation worker."""
    asyncio.run(_prep_worker(once, interval))


async def _prep_worker(once: bool, interval: int):
    from voulezvous.database import async_session
    from voulezvous.services.prep_worker import run_prep_cycle

    while True:
        async with async_session() as db:
            processed = await run_prep_cycle(db)
            click.echo(f"Prep cycle: processed {processed} items")
        if once:
            break
        await asyncio.sleep(interval)


@cli.command("streamer")
def streamer_cmd():
    """Run the streamer process."""
    asyncio.run(_streamer())


async def _streamer():
    from voulezvous.services.streamer import run_streamer

    await run_streamer()


@cli.command("reporter")
@click.option("--date", "report_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
def reporter_cmd(report_date):
    """Generate a daily report."""
    asyncio.run(_reporter(report_date.date() if hasattr(report_date, "date") else report_date))


async def _reporter(report_date: date):
    from voulezvous.database import async_session
    from voulezvous.services.reporter import generate_daily_report

    async with async_session() as db:
        report = await generate_daily_report(db, report_date)
        click.echo(report.markdown_text)


# ==========================================================================
# Acquisition subsystem CLI commands
# ==========================================================================


@cli.command("seed-acquisition-data")
def seed_acquisition_data_cmd():
    """Seed demo data for the acquisition subsystem."""
    asyncio.run(_seed_acquisition())


async def _seed_acquisition():
    from voulezvous.acquisition.seed import seed_acquisition_data
    from voulezvous.database import async_session

    async with async_session() as db:
        result = await seed_acquisition_data(db)
        click.echo(f"Acquisition seed: {result}")


@cli.command("discovery-worker")
@click.argument("action", type=click.Choice(["run"]))
def discovery_worker_cmd(action: str):
    """Run a discovery cycle (simulated for demo)."""
    asyncio.run(_discovery_worker())


async def _discovery_worker():
    from voulezvous.acquisition.workers.discovery import run_discovery_simulated
    from voulezvous.database import async_session

    async with async_session() as db:
        run = await run_discovery_simulated(db)
        click.echo(f"Discovery run {run.id}: {run.output_summary}")


@cli.command("enrichment-worker")
@click.argument("action", type=click.Choice(["run"]))
def enrichment_worker_cmd(action: str):
    """Run enrichment on un-enriched candidates."""
    asyncio.run(_enrichment_worker())


async def _enrichment_worker():
    from voulezvous.acquisition.workers.enrichment import run_enrichment
    from voulezvous.database import async_session

    async with async_session() as db:
        result = await run_enrichment(db)
        click.echo(f"Enrichment: {result}")


@cli.command("curator-planner")
@click.argument("action", type=click.Choice(["generate"]))
@click.option("--date", "lineup_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--hours", default=24, type=int)
@click.option("--mix-music", is_flag=True, default=True)
def curator_planner_cmd(action: str, lineup_date, hours: int, mix_music: bool):
    """Generate a 24h lineup from approved shelf."""
    d = lineup_date.date() if hasattr(lineup_date, "date") else lineup_date
    asyncio.run(_curator_planner(d, hours, mix_music))


async def _curator_planner(lineup_date, hours, mix_music):
    from voulezvous.acquisition.workers.curator import generate_lineup
    from voulezvous.database import async_session

    async with async_session() as db:
        lineup = await generate_lineup(db, lineup_date, hours, mix_music)
        click.echo(
            f"Lineup {lineup.id} for {lineup_date}: "
            f"{lineup.context_summary.get('total_items', 0)} items, "
            f"{lineup.context_summary.get('total_duration_hours', 0)}h"
        )


@cli.command("media-ir-compiler")
@click.argument("action", type=click.Choice(["run"]))
@click.option("--lineup-id", required=True)
def media_ir_compiler_cmd(action: str, lineup_id: str):
    """Compile Media IR for a lineup."""
    import uuid

    asyncio.run(_media_ir_compiler(uuid.UUID(lineup_id)))


async def _media_ir_compiler(lineup_id):
    from voulezvous.acquisition.workers.media_ir import compile_media_ir
    from voulezvous.database import async_session

    async with async_session() as db:
        result = await compile_media_ir(db, lineup_id)
        click.echo(f"Media IR: {result}")


@cli.command("acq-reporter")
@click.argument("action", type=click.Choice(["generate"]))
@click.option("--date", "report_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
def acq_reporter_cmd(action: str, report_date):
    """Generate an autonomy report."""
    d = report_date.date() if hasattr(report_date, "date") else report_date
    asyncio.run(_acq_reporter(d))


async def _acq_reporter(report_date):
    from voulezvous.acquisition.workers.reporter import generate_report
    from voulezvous.database import async_session

    async with async_session() as db:
        report = await generate_report(db, report_date)
        click.echo(report.markdown_text)


@cli.command("orchestrator")
@click.argument("action", type=click.Choice(["run-daily"]))
@click.option("--date", "target_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def orchestrator_cmd(action: str, target_date):
    """Run the full autonomous daily orchestration cycle."""

    d = None
    if target_date:
        d = target_date.date() if hasattr(target_date, "date") else target_date
    asyncio.run(_orchestrator(d))


async def _orchestrator(target_date):
    from voulezvous.acquisition.workers.orchestrator import run_daily_orchestration
    from voulezvous.database import async_session

    async with async_session() as db:
        result = await run_daily_orchestration(db, target_date)
        click.echo(f"Orchestration result: {result}")


if __name__ == "__main__":
    cli()
