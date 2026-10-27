"""Same-origin loopback API and production React assets. No automatic broker actions."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, StrictFloat

from goxtrade.api import state
from goxtrade.config import execution_identity as identity
from goxtrade.paths import ROOT

PORT = int(os.environ.get("GOX_NATIVE_PORT", "8504"))
ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
DIST = ROOT / "web" / "dist"
Profile = Literal["practice", "leader"]
Count = Annotated[StrictInt, Field(ge=1, le=4)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Policy(Body):
    strategies: list[str]
    quantities: dict[str, Count]
    cooldown: Annotated[StrictInt, Field(ge=1, le=60)]
    enable_mym: StrictBool
    symbols: list[Literal['MNQ','MES','MYM']] | None = None


class Intervals(Body):
    stop_minutes: Literal[5, 10, 15]
    orb_minutes: Literal[5, 15, 30]


class Credentials(Body):
    username: Annotated[str, Field(min_length=1, max_length=200)]
    api_key: SecretStr


class Replacement(Body):
    account_id: Annotated[StrictInt, Field(gt=0)]
    name: Annotated[str, Field(min_length=1, max_length=160)]
    confirmed: StrictBool


class Authorization(Body):
    name: str
    safeguards: StrictBool
    acknowledge_loss: StrictBool = False
    strategies: list[str] = Field(default_factory=list,max_length=7)
    quantities: dict[str,Count] | None = None


class ClearAlerts(Body):
    ids: list[StrictInt] = Field(max_length=200)


class SafeguardSave(Body):
    revision: Annotated[StrictInt,Field(ge=0)]
    loss_lock: Annotated[StrictFloat,Field(gt=0,le=1000000)]
    max_contracts: Count
    max_trade_risk: Annotated[StrictFloat,Field(gt=0,le=1000000)]
    max_open_risk: Annotated[StrictFloat,Field(gt=0,le=1000000)]
    overnight_max_contracts: Count
    overnight_cooldown_minutes: Annotated[StrictInt,Field(ge=0,le=1440)]
    overnight_max_spread_ticks: Annotated[StrictInt,Field(ge=1,le=100)]


class SafeguardApply(Body):
    name: str
    revision: Annotated[StrictInt,Field(ge=0)]
    confirmed: StrictBool


class Instrument(Body):
    symbol: Annotated[str, Field(min_length=1, max_length=32)]
    contract_id: str = ""


class Research(Body):
    symbol: Literal["MNQ", "MES", "MYM", "NQ", "ES", "YM"]
    contract_id: str
    strategy: str = "VWAP EMA Cross"
    csv: str = Field(min_length=1, max_length=1500000)
    commission: Annotated[float, Field(ge=0)]
    zero_cost_sensitivity: StrictBool = False
    slippage: Annotated[StrictInt, Field(ge=0, le=100)] = 1
    quantity: Count = 1
    walk_forward: StrictBool = False


class PortfolioDataset(Body):
    symbol: Literal["MNQ", "MES", "MYM", "NQ", "ES", "YM"]
    contract_id: Annotated[str, Field(min_length=1, max_length=100)]
    csv: str = Field(min_length=1, max_length=1500000)


class PortfolioResearch(Body):
    datasets: list[PortfolioDataset] = Field(min_length=1, max_length=3)
    walk_forward: StrictBool = False
    compare: StrictBool = False


def session(request: Request):
    key = request.cookies.get("gox_session", "")
    stored = request.app.state.sessions.get(key)
    if not stored or stored[1] < time.monotonic():
        raise HTTPException(401, "Local session expired. Reload the workspace.")
    return stored[0]


def mutation(request: Request, csrf=Depends(session)):
    if request.headers.get("origin") not in ORIGINS or not secrets.compare_digest(request.headers.get("x-gox-csrf", ""), csrf):
        raise HTTPException(403, "Same-origin confirmation required")


@asynccontextmanager
async def lifespan(app):
    # No collector, broker login, order submission or arming in the web lifespan.
    yield


def create_app():
    app = FastAPI(title="GoXTrade local API", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.sessions = {}
    app.state.sockets = 0
    app.state.action_lock = asyncio.Lock()

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.headers.get("host") not in HOSTS:
            return JSONResponse({"detail": "Loopback host required"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site access denied"}, status_code=403)
        length=request.headers.get("content-length", "0")
        if not length or not length.isascii() or not length.isdecimal() or len(length)>10:
            return JSONResponse({"detail": "Invalid request length"}, status_code=400)
        if int(length) > 1800000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's raw error inputs can contain API keys: never echo them.
        return JSONResponse({"detail": "Invalid request values", "fields": [".".join(map(str, e["loc"])) for e in error.errors()]}, status_code=422)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)[:400]}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        return JSONResponse({"detail": "Operation failed. Verify broker connectivity and current state before retrying."}, status_code=503)

    @app.get("/api/health")
    def health():
        return dict(app="goxtrade-native", workspace=hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])

    @app.get("/api/session")
    def establish(request: Request):
        cookie = request.cookies.get("gox_session", "")
        existing = app.state.sessions.get(cookie)
        if not existing or existing[1] < time.monotonic():
            cookie = secrets.token_urlsafe(32)
            existing = (secrets.token_urlsafe(32), time.monotonic()+28800)
            expired = [key for key, row in app.state.sessions.items() if row[1] < time.monotonic()]
            for key in expired:
                app.state.sessions.pop(key, None)
            if len(app.state.sessions) >= 64:
                raise HTTPException(429, "Too many local browser sessions")
            app.state.sessions[cookie] = existing
        response = JSONResponse(dict(csrf=existing[0]))
        response.set_cookie("gox_session", cookie, httponly=True, samesite="strict", max_age=28800)
        return response

    @app.get("/api/config", dependencies=[Depends(session)])
    def config():
        return state.configuration()

    @app.get("/api/snapshot", dependencies=[Depends(session)])
    def snapshot():
        return dict(**state.CACHE.get(), **state.ticks())

    @app.websocket("/api/stream")
    async def stream(socket: WebSocket):
        key = socket.cookies.get("gox_session", "")
        stored = app.state.sessions.get(key)
        if (socket.headers.get("host") not in HOSTS or socket.headers.get("origin") not in ORIGINS
                or not stored or stored[1] < time.monotonic() or app.state.sockets >= 8):
            await socket.close(code=1008)
            return
        app.state.sockets += 1
        await socket.accept()
        previous = None
        pending_snapshot = None
        try:
            while stored[1] >= time.monotonic():
                prices = await asyncio.to_thread(state.ticks)
                await asyncio.wait_for(socket.send_json(dict(type="ticks", data=prices)), timeout=5)
                # Heavy attribution snapshots never hold up the fresh-price channel.
                if pending_snapshot is None:
                    pending_snapshot = asyncio.create_task(asyncio.to_thread(state.CACHE.get))
                if pending_snapshot.done():
                    current = pending_snapshot.result()
                    pending_snapshot = None
                    if current is not previous:
                        await asyncio.wait_for(socket.send_json(dict(type="snapshot", data=current)), timeout=5)
                        previous = current
                await asyncio.sleep(.25)
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            if pending_snapshot is not None:
                pending_snapshot.cancel()
            app.state.sockets -= 1
            try:
                await socket.close()
            except RuntimeError:
                pass

    @app.get("/api/chart", dependencies=[Depends(session)])
    def chart(symbol: Literal["NQ=F", "ES=F", "YM=F", "MNQ=F", "MES=F", "MYM=F"], minutes: Annotated[int, Query(ge=1, le=60)] = 1, hours: Annotated[int, Query(ge=24, le=48)] = 48):
        if minutes not in (1, 3, 5, 15, 30, 60) or hours not in (24, 48):
            raise ValueError("Unsupported chart candle interval or range")
        return chart_data(symbol, minutes, hours)

    @app.post("/api/policy/{profile}", dependencies=[Depends(mutation)])
    def policy(profile: Profile, body: Policy):
        identity.assert_current(profile)
        from goxtrade.bot import bot_controls
        from goxtrade.execution import practice_executor, leader_execution
        from goxtrade.strategies.strategy_catalog import strategy_spec
        if set(body.quantities) != {"MNQ", "MES", "MYM"} or any(profile not in strategy_spec(name).execution_profiles for name in body.strategies):
            raise ValueError("Unsupported sizing or strategy for this profile")
        symbols = body.symbols
        if symbols is None:
            symbols=[s for s in bot_controls.read(profile)['symbols'] if s in ('MNQ','MES')]+(['MYM'] if body.enable_mym else [])
        if len(set(symbols))!=len(symbols) or ('MYM' in symbols)!=body.enable_mym:
            raise ValueError('Choose unique instruments and matching MYM activation')
        if profile == "leader":
            leader_execution.command("configure", quantities=body.quantities, strategies=body.strategies, cooldown=body.cooldown, enable_mym=body.enable_mym,symbols=symbols)
        else:
            bot_controls.save(symbols, body.strategies, body.cooldown, profile="practice")
            practice_executor.configure(body.quantities, body.enable_mym)
        state.CACHE.invalidate()
        return dict(message="Policy saved. Run/Pause state unchanged.")

    @app.post("/api/intervals", dependencies=[Depends(mutation)])
    def intervals(body: Intervals):
        from goxtrade.strategies import strategy_settings
        strategy_settings.save_stop_minutes(body.stop_minutes)
        strategy_settings.save_orb_minutes(body.orb_minutes)
        return dict(message="Intervals saved for new setups. Open positions are unchanged.")

    @app.get('/api/safeguards/{profile}',dependencies=[Depends(session)])
    def safeguards_view(profile: Profile):
        from goxtrade.execution.safeguards import read
        return read(identity.current_targets()[profile]['gate_id'])

    @app.post('/api/safeguards/{profile}',dependencies=[Depends(mutation)])
    async def safeguards_save(profile: Profile,body: SafeguardSave):
        from goxtrade.execution.safeguards import save
        async with app.state.action_lock:
            identity.assert_current(profile)
            record=await asyncio.to_thread(save,identity.TARGETS[profile]['gate_id'],body.model_dump(exclude={'revision'}),body.revision)
        state.CACHE.invalidate()
        return dict(message='Safeguards saved. Active limits and trading authorization are unchanged.',**record)

    @app.post('/api/safeguards/{profile}/apply',dependencies=[Depends(mutation)])
    async def safeguards_apply(profile: Profile,body: SafeguardApply):
        from goxtrade.execution.safeguards import apply
        if body.confirmed is not True:
            raise ValueError('Confirm the reviewed account safeguard values')
        async with app.state.action_lock:
            record=await asyncio.to_thread(apply,profile,body.name,body.revision)
        state.CACHE.invalidate()
        return dict(message='Safeguards applied. Loss baseline, latched locks and Run/Pause state are unchanged.',**record)

    @app.post("/api/vwap", dependencies=[Depends(mutation)])
    def vwap(values: dict):
        from goxtrade.strategies.strategy_settings import save_vwap_ema_config
        from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
        config = VwapEmaConfig.from_dict(values)
        if config.paper_enabled and not config.paper_commission_per_side and not config.paper_zero_cost_sensitivity:
            raise ValueError("Paper fees must be explicit or an acknowledged zero-cost sensitivity scenario")
        save_vwap_ema_config(config)
        return dict(message="VWAP settings saved. No account armed.")

    @app.post("/api/previous-day-box", dependencies=[Depends(mutation)])
    def previous_box_settings(values: dict):
        from goxtrade.strategies.strategy_settings import save_previous_day_box_config
        save_previous_day_box_config(values)
        return dict(message="Previous Day Box settings saved. Account authorization remains independent; no account armed.")

    @app.get("/api/previous-day-box/{symbol}", dependencies=[Depends(session)])
    def previous_box_view(symbol: Literal["NQ=F","ES=F","YM=F","MNQ=F","MES=F","MYM=F"]):
        from goxtrade.data.previous_box_view import view
        return state.clean(view(symbol))

    @app.post("/api/credentials", dependencies=[Depends(mutation)])
    def credentials(body: Credentials):
        from contextlib import closing
        from goxtrade.data.live_store import connect
        from goxtrade.execution.account_management import assert_idle, assert_workers_stopped
        from goxtrade.execution.projectx_client import save_credentials
        assert_workers_stopped(action="changing API credentials. Use Connection > Market worker > Pause & stop trading workers first")
        with closing(connect()) as conn:
            assert_idle(conn, action="changing API credentials")
        save_credentials(body.username, body.api_key.get_secret_value())
        return dict(message="Credentials saved locally. Restart workers after changing the login.")

    @app.post("/api/connection/test", dependencies=[Depends(mutation)])
    def connection_test():
        from goxtrade.execution.projectx_client import login
        try:
            login()
        except Exception:
            raise HTTPException(503, "ProjectX authentication unavailable. Check the key, network and provider access.")
        return dict(message="Authentication succeeded. No orders submitted.")

    @app.post("/api/accounts/refresh", dependencies=[Depends(mutation)])
    def account_refresh():
        from goxtrade.execution.live_accounts import enabled_accounts, search_accounts, copy_role
        return dict(accounts=[dict(**row, copy_role=copy_role(row)) for row in enabled_accounts(search_accounts())])

    @app.post("/api/accounts/{profile}/replace", dependencies=[Depends(mutation)])
    def replace(profile: Profile, body: Replacement):
        if not body.confirmed:
            raise ValueError("Confirm flat accounts, stopped workers and verified copier setup")
        from goxtrade.execution.account_management import replace_account
        replace_account(profile, body.account_id, body.name)
        state.CACHE.invalidate()
        return dict(message="Replacement saved. Restart the interface and workers before explicit authorization.")

    @app.post("/api/execution/{profile}/{action}", dependencies=[Depends(mutation)])
    async def execution(profile: Profile, action: Literal["arm", "pause", "emergency", "monitor", "start"], body: Authorization):
        async with app.state.action_lock:
            return await asyncio.to_thread(execute, profile, action, body)

    @app.get("/api/services", dependencies=[Depends(session)])
    def service_status():
        from goxtrade.runtime.service_control import status
        return status()

    @app.post("/api/services/{action}", dependencies=[Depends(mutation)])
    async def service_action(action: Literal["start", "restart", "stop"]):
        from goxtrade.runtime.service_control import command
        async with app.state.action_lock:
            result = await asyncio.to_thread(command, action)
            state.CACHE.invalidate()
            return result

    @app.post("/api/workers/{action}", dependencies=[Depends(mutation)])
    async def workers(action: Literal["start", "stop"]):
        async with app.state.action_lock:
            return await asyncio.to_thread(worker_action, action)

    def worker_action(action):
        from goxtrade.runtime import live_process
        from goxtrade.runtime.manage_app import stop_workers
        if action == "start":
            identity.assert_current("practice")
            identity.assert_current("leader")
            from goxtrade.execution.projectx_client import credentials_present
            if not credentials_present():
                raise ValueError("Configure credentials first")
            return live_process.start()
        stop_workers()
        return dict(message="Trading workers stopped after broker-flat verification. Interface remains open.")

    @app.post("/api/alerts/clear", dependencies=[Depends(mutation)])
    def clear(body: ClearAlerts):
        from goxtrade.bot.watch_alerts import clear_watch_alerts
        count = clear_watch_alerts(body.ids)
        state.CACHE.invalidate()
        return dict(message=f"Cleared {count} watch-only alerts. Open and uncertain orders remain protected.")

    @app.post("/api/instruments", dependencies=[Depends(mutation)])
    def instrument(body: Instrument):
        from goxtrade.data.symbol_store import add_symbol
        from goxtrade.execution.contracts import is_valid_contract_id, save_contract
        if body.contract_id and not is_valid_contract_id(body.contract_id):
            raise ValueError("Invalid contract mapping")
        ok, message = add_symbol(body.symbol)
        if ok and body.contract_id:
            save_contract(body.symbol.strip().upper(), body.contract_id)
        if not ok:
            raise ValueError(message)
        return dict(message=message)

    @app.delete("/api/instruments/{symbol}", dependencies=[Depends(mutation)])
    def remove_instrument(symbol: str):
        from goxtrade.data.symbol_store import remove_symbol
        remove_symbol(symbol)
        return dict(message="Watchlist instrument removed; execution permissions unchanged.")

    @app.post("/api/history/{symbol}", dependencies=[Depends(mutation)])
    def history(symbol: Literal["NQ=F", "ES=F", "YM=F", "MNQ=F", "MES=F", "MYM=F"]):
        from goxtrade.data.chart_history import backfill_history
        return dict(message=f"Retrieved {backfill_history(symbol)} actual contract bars.")

    @app.get("/api/manager", dependencies=[Depends(session)])
    def manager_view(profile: Profile = "practice"):
        from goxtrade.execution.manager_service import overview
        return state.clean(overview(profile))

    @app.get("/api/replay", dependencies=[Depends(session)])
    def replay_overview():
        from goxtrade.replay.replay_session import overview
        return overview()

    @app.post("/api/replay", dependencies=[Depends(mutation)])
    def replay_create(body:dict):
        from goxtrade.replay.replay_session import create
        return create(body)

    @app.post("/api/replay/ticks", dependencies=[Depends(mutation)])
    def replay_ticks(body:dict):
        from goxtrade.replay.replay_adapter import import_ticks
        return import_ticks(body)

    @app.post("/api/replay/ticks/saved", dependencies=[Depends(mutation)])
    def replay_saved_ticks(body:dict):
        from goxtrade.replay.replay_adapter import import_saved_ticks
        return import_saved_ticks(body)

    @app.get("/api/replay/{identifier}", dependencies=[Depends(session)])
    def replay_detail(identifier:str):
        from goxtrade.replay.replay_session import detail
        return detail(identifier)

    @app.post("/api/replay/{identifier}/control", dependencies=[Depends(mutation)])
    def replay_control(identifier:str,body:dict):
        from goxtrade.replay.replay_session import action
        return action(identifier,body)

    @app.get("/api/replay/{identifier}/chart", dependencies=[Depends(session)])
    def replay_chart(identifier:str,symbol:str):
        from goxtrade.replay.replay_session import chart
        return chart(identifier,symbol)

    @app.get("/api/replay/{identifier}/export", dependencies=[Depends(session)])
    def replay_export(identifier:str):
        from goxtrade.replay.replay_store import get
        return get(identifier)

    @app.get("/api/diagnostics", dependencies=[Depends(session)])
    def diagnostics_view():
        from goxtrade.diagnostics.projectx_diagnostics import overview
        return overview()

    @app.post("/api/diagnostics", dependencies=[Depends(mutation)])
    def diagnostics_probe(body:dict):
        from goxtrade.diagnostics.projectx_diagnostics import run
        return run(body)

    @app.get("/api/validation-lab", dependencies=[Depends(session)])
    def validation_lab_view():
        from goxtrade.research.lab_service import overview
        return state.clean(overview())

    @app.post("/api/validation-lab/history", dependencies=[Depends(mutation)])
    def validation_lab_history(body: dict):
        from goxtrade.research.lab_service import history
        return dict(message="Read-only historical download requested",job=history(body))

    @app.post("/api/validation-lab/import", dependencies=[Depends(mutation)])
    def validation_lab_import(body: dict):
        from goxtrade.research.lab_service import import_csv
        return state.clean(dict(message="Research dataset imported; quality gates apply",dataset=import_csv(body)))

    @app.post("/api/validation-lab/import-saved", dependencies=[Depends(mutation)])
    def validation_lab_import_saved(body: dict):
        from goxtrade.research.lab_service import import_saved
        return state.clean(dict(message="Canonical history snapshotted for isolated research",dataset=import_saved(body)))

    @app.post("/api/validation-lab/run", dependencies=[Depends(mutation)])
    def validation_lab_run(body: dict):
        from goxtrade.research.lab_service import validation
        return dict(message="Historical research queued; no broker execution",job=validation(body))

    @app.post("/api/validation-lab/jobs/{identifier}/{action}", dependencies=[Depends(mutation)])
    def validation_lab_job(identifier: str, action: Literal["resume","cancel"]):
        from goxtrade.research.lab_jobs import start,cancel
        return dict(message="Research job "+action,job=start(identifier) if action=="resume" else cancel(identifier))

    @app.get("/api/validation-lab/datasets/{identifier}/export", dependencies=[Depends(session)])
    def validation_lab_dataset_export(identifier: str):
        from goxtrade.research.lab_reports import export_dataset
        from goxtrade.data.lab_store import get
        get("lab_datasets",identifier)
        return StreamingResponse(export_dataset(identifier),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=historical-minutes.csv"})

    @app.get("/api/validation-lab/runs/{identifier}", dependencies=[Depends(session)])
    def validation_lab_result(identifier: str):
        from goxtrade.data.lab_store import get
        return state.clean(get("lab_runs",identifier))

    @app.get("/api/validation-lab/runs/{identifier}/export", dependencies=[Depends(session)])
    def validation_lab_report(identifier: str, format: Literal["csv","html"]="html"):
        from goxtrade.data.lab_store import get
        from goxtrade.research.lab_reports import trades_csv,html_report
        run = get("lab_runs",identifier)
        return Response(html_report(run) if format=="html" else trades_csv(run),media_type="text/html" if format=="html" else "text/csv",
                        headers={"Content-Disposition":"attachment; filename=validation-report."+format,"Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'"})

    @app.get("/api/validation-lab/runs/{identifier}/trades/{index}", dependencies=[Depends(session)])
    def validation_lab_trade(identifier: str,index: int):
        from goxtrade.data.lab_store import get
        from goxtrade.research.validation_lab import trade_window
        return state.clean(trade_window(get("lab_runs",identifier),index))

    @app.get("/api/trade-management", dependencies=[Depends(session)])
    def trade_management_view(profile: Profile = "practice"):
        from goxtrade.execution.profit_service import view
        return state.clean(view(profile))

    @app.post("/api/trade-management/policy", dependencies=[Depends(mutation)])
    def trade_management_policy(body: dict):
        from goxtrade.execution.profit_service import save_policy
        return dict(message="New research/paper exit policy saved. Existing positions and broker controls unchanged.", policy=save_policy(body).to_dict())

    @app.post("/api/trade-management/compare", dependencies=[Depends(mutation)])
    def trade_management_compare(body: PortfolioResearch):
        import pandas as pd
        from io import StringIO
        from goxtrade.execution.manager_service import policy, shared_strategy_configs
        from goxtrade.execution.profit_service import save_comparison
        from goxtrade.research.exit_policy_comparison import compare_exits, chronological_exit_folds
        datasets = [(item.symbol, item.contract_id, pd.read_csv(StringIO(item.csv))) for item in body.datasets]
        if sum(len(frame) for _, _, frame in datasets) > 10000:
            raise ValueError("Use at most 10000 actual source minutes for interactive ten-policy comparison")
        settings, configs = policy(), shared_strategy_configs()
        result = compare_exits(datasets, settings, configs)
        if body.walk_forward:
            result["walk_forward"] = chronological_exit_folds(datasets, settings, configs)
        return state.clean(dict(message="Prespecified exit-policy research saved separately from broker results.", id=save_comparison(result), result=result))

    @app.post("/api/manager/policy", dependencies=[Depends(mutation)])
    def manager_policy(body: dict):
        from goxtrade.execution.manager_service import save_policy
        result = save_policy(body)
        return dict(message="Research manager policy saved. Broker settings and arming unchanged.", policy=result.to_dict())

    @app.post("/api/manager/evaluate/{profile}", dependencies=[Depends(mutation)])
    def manager_shadow(profile: Profile):
        from goxtrade.execution.manager_service import shadow
        return state.clean(dict(message="Shadow decisions recorded. No broker authorization.", result=shadow(profile, persist=True)))

    @app.post("/api/manager/paper", dependencies=[Depends(mutation)])
    def manager_paper():
        from goxtrade.execution.manager_service import paper_once
        return state.clean(dict(message="Separate portfolio paper state evaluated; no broker orders.", result=paper_once()))

    @app.post("/api/manager/paper/start", dependencies=[Depends(mutation)])
    def manager_paper_start():
        from goxtrade.runtime.manager_paper_worker import start
        return dict(message=start())

    @app.post("/api/manager/backtest", dependencies=[Depends(mutation)])
    def manager_backtest(body: PortfolioResearch):
        from io import StringIO
        import pandas as pd
        from goxtrade.execution.manager_service import policy, shared_strategy_configs, save_simulation
        from goxtrade.research.portfolio_backtest import run_portfolio_backtest, compare_portfolios, walk_forward
        datasets = [(item.symbol, item.contract_id, pd.read_csv(StringIO(item.csv))) for item in body.datasets]
        if sum(len(frame) for _, _, frame in datasets) > 20000:
            raise ValueError("Use at most 20000 actual minute bars per interactive portfolio run")
        settings, configs = policy(), shared_strategy_configs()
        from goxtrade.execution.profit_service import read_policy as profit_policy
        exits = profit_policy()
        result = run_portfolio_backtest(datasets, settings, configs, profit_policy=exits)
        if body.compare:
            result["comparisons"] = {key: value["summary"] for key, value in compare_portfolios(datasets, settings, configs, profit_policy=exits).items()}
        if body.walk_forward:
            result["walk_forward"] = [{key: value for key, value in row.items() if key != "result"} | dict(summary=row["result"]["summary"]) for row in walk_forward(datasets, settings, configs, profit_policy=exits)]
        identifier = save_simulation(result)
        return state.clean(dict(message="Chronological portfolio simulation saved separately from broker results.", id=identifier, result=result))

    @app.get("/api/research", dependencies=[Depends(session)])
    def research_runs():
        from goxtrade.research.result_store import saved_runs
        from goxtrade.research.forward_paper import paper_trades
        from goxtrade.research.metrics import breakdown
        return state.clean(dict(runs=saved_runs(),paper_summary=breakdown(paper_trades(),"strategy")))

    @app.post("/api/research", dependencies=[Depends(mutation)])
    def research(body: Research):
        from io import StringIO
        import pandas as pd
        from goxtrade.research.backtest import SimulationConfig, run_backtest
        from goxtrade.research.result_store import save_run
        from goxtrade.strategies.strategy_settings import read_vwap_ema_config
        source = pd.read_csv(StringIO(body.csv))
        if len(source) > 15000:
            raise ValueError("Use at most 15000 actual minute bars per interactive research run")
        from goxtrade.strategies.strategy_catalog import strategy_spec
        spec = strategy_spec(body.strategy)
        if spec.id=="previous_day_box":
            from goxtrade.strategies.strategy_settings import read_previous_day_box_config
            config = read_previous_day_box_config()
        else:
            config = read_vwap_ema_config() if spec.id=="vwap_ema_cross" else None
        sim = SimulationConfig(quantity=body.quantity, commission_per_side=body.commission, zero_cost_sensitivity=body.zero_cost_sensitivity, slippage_ticks=body.slippage)
        result = run_backtest(source, body.symbol, body.contract_id, strategy=body.strategy, strategy_config=config, simulation=sim)
        if body.walk_forward:
            from goxtrade.research.backtest import chronological_splits as walk_forward
            result["walk_forward"] = walk_forward(source,body.symbol,body.contract_id,strategy=body.strategy,strategy_config=config,simulation=sim)
        number = save_run(dict(symbol=body.symbol, contract_id=body.contract_id), result)
        return state.clean(dict(message="Simulated research saved separately from broker results.", id=number, result=result))

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST/"assets"), name="assets")

    @app.get("/{path:path}")
    def index(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        if not (DIST/"index.html").exists():
            raise HTTPException(503, "Frontend is not built. Run npm ci and npm run build in web/.")
        return FileResponse(DIST/"index.html", headers={"Cache-Control": "no-cache"})

    return app


def execute(profile, action, body):
    from goxtrade.execution import practice_executor, leader_execution
    target = identity.TARGETS[profile]
    if action=="start" and profile!="practice":
        raise ValueError("Practice automation cannot authorize Leader")
    if action=="arm" and profile=="practice":
        raise ValueError("Legacy Practice start is disabled; use manager-controlled automation")
    if action in ("arm", "emergency", "start") and (body.name != target["name"] or not body.safeguards):
        raise ValueError("Confirm the exact execution account and protective/copy safeguards")
    if action in ("arm", "monitor", "start"):
        identity.assert_current(profile)
    if action in ("arm", "start"):
        from datetime import datetime, timezone
        runtime = (practice_executor.snapshot() if profile == "practice" else leader_execution.snapshot())[1]
        try:
            elapsed = (datetime.now(timezone.utc)-datetime.fromisoformat(runtime["updated_at"])).total_seconds()
        except (KeyError, ValueError, TypeError):
            elapsed = float("inf")
        if not 0 <= elapsed < 45 or runtime.get("account_id") != target["id"]:
            raise ValueError("A fresh worker for this exact account must be online before authorization")
        from goxtrade.execution.safeguards import PROTOCOL_VERSION
        from goxtrade.runtime.build_identity import fingerprint
        if runtime.get('worker_build')!=fingerprint():
            raise ValueError('Restart the paused account worker while flat to load the installed build before authorization')
        if runtime.get('safeguards_version')!=PROTOCOL_VERSION:
            raise ValueError('Restart the account worker to load configurable safeguard enforcement before authorization')
        if action == "start" and runtime.get("practice_automation") is not True:
            raise ValueError("Restart the paused Practice worker to load production automation before starting")
    if profile == "leader":
        if action == "monitor":
            leader_execution.start_worker()
        elif action == "arm":
            settings = leader_execution.snapshot()[0]
            leader_execution.command("arm", confirmed_account=target["name"], copier_confirmed=True,
                                     acknowledge_loss=body.acknowledge_loss, quantities=settings.get("quantities", dict(MNQ=2, MES=2, MYM=2)))
        else:
            leader_execution.command(action, confirmed_account=target["name"])
    else:
        if action == "start":
            from goxtrade.execution.practice_automation import start
            start(body.strategies,body.name,body.safeguards,confirmed_quantities=body.quantities,acknowledge_loss=body.acknowledge_loss)
        elif action == "pause":
            practice_executor.pause()
        elif action == "emergency":
            practice_executor.request_emergency_close(True)
        else:
            raise ValueError("Practice monitoring is part of the separately started market worker")
    state.CACHE.invalidate()
    return dict(message="Request recorded. Broker fills and worker status remain authoritative.")


_chart_cache = {}
_chart_lock = __import__("threading").Lock()


def chart_data(symbol, minutes, hours):
    key = (symbol, minutes, hours)
    with _chart_lock:
        cached = _chart_cache.get(key)
        if cached and time.monotonic()-cached[0] < 2:
            return cached[1]
        from goxtrade.data.chart_history import chart_history
        from goxtrade.market.chart_indicators import indicator_points
        # Local history only. Explicit POST recovery is the only broker backfill path.
        points = indicator_points(chart_history(symbol, hours=hours), f"{minutes}min")
        value = state.clean(dict(symbol=symbol, minutes=minutes, points=points))
        if len(_chart_cache) > 40:
            _chart_cache.clear()
        _chart_cache[key] = (time.monotonic(), value)
        return value


app = create_app()
