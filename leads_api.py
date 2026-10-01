"""
B2B-лиды (закрытая CRM для основателей). Подключается из bot.py одним вызовом setup_leads().

Что внутри:
  * GET  /api/leads/access          — тихая проверка прав (как /api/admin/me): founder true/false
  * GET  /api/leads                 — список лидов (только основатели; остальным 404)
  * POST /api/leads/{id}/status     — смена статуса, пишет leads.json
  * пуш напарнику при смене статуса и ежедневный дайджест «по этим лидам давно нет движения»

Авторизация — тот же current_user из bot.py (подпись initData проверяет он), здесь только список FOUNDER_IDS.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from leads_store import NICHES, STATUSES, LeadStore, stale_leads

log = logging.getLogger("elevate.leads")
BASE = Path(__file__).parent


# ───────────────────────── Чистые функции (тестируются без FastAPI) ─────────────────────────
def build_digest(leads: list[dict], limit: int = 8) -> str | None:
    stale = stale_leads(leads)
    if not stale:
        return None
    lines = ["<b>B2B-лиды: по этим заведениям давно нет движения</b>", ""]
    for l in stale[:limit]:
        lines.append(f"• <b>{escape(l['name'])}</b> ({escape(l['address'])}) — "
                     f"«{escape(STATUSES[l['status']])}» уже {l['_age_days']} дн.")
    if len(stale) > limit:
        lines.append(f"…и ещё {len(stale) - limit}")
    return "\n".join(lines)


def change_text(actor_name: str, lead: dict, old: str) -> str:
    return (f"<b>{escape(actor_name)}</b>: {escape(lead['name'])} — "
            f"{escape(STATUSES[old])} → <b>{escape(STATUSES[lead['status']])}</b>")


def moscow_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Moscow"))
    except Exception:  # нет tzdata на минимальном образе
        return datetime.now(timezone(timedelta(hours=3)))


def digest_due(now: datetime, last_sent: str | None, hour: int) -> bool:
    """По будням, не раньше hour и не позже 20:00 (чтобы проснувшийся ночью сервис не будил пушем)."""
    return now.weekday() < 5 and hour <= now.hour < 20 and last_sent != now.date().isoformat()


# ───────────────────────── Модуль ─────────────────────────
class LeadsModule:
    def __init__(self, bot, founder_ids: set[int], webapp_url: str, data_dir: str | os.PathLike):
        self.bot = bot
        self.founder_ids = set(founder_ids)
        self.webapp_url = (webapp_url or "").rstrip("/")
        self.store = LeadStore(Path(data_dir) / "leads.json", BASE / "leads_seed.csv")
        self._tasks: set[asyncio.Task] = set()

    # --- жизненный цикл ---
    async def startup(self) -> None:
        added = await asyncio.to_thread(self.store.sync_seed)
        log.info("Leads: leads.json готов (%s), новых лидов из CSV: %s, основателей: %s",
                 self.store.path, added, len(self.founder_ids))
        if not self.founder_ids:
            log.warning("FOUNDER_IDS не задан — раздел «B2B Лиды» закрыт для всех")

    async def reminder_loop(self) -> None:
        hour = int(os.getenv("LEADS_DIGEST_HOUR", "10"))
        while True:
            try:
                last = await asyncio.to_thread(self.store.get_meta, "last_digest")
                if self.founder_ids and digest_due(moscow_now(), last, hour):
                    # отметка ДО отправки: при падении лучше пропустить один пуш, чем слать дубли
                    await asyncio.to_thread(self.store.set_meta, "last_digest", moscow_now().date().isoformat())
                    text = build_digest(await asyncio.to_thread(self.store.list_leads))
                    if text:
                        for fid in self.founder_ids:
                            await self._send(fid, text)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("leads reminder_loop error")
            await asyncio.sleep(600)

    # --- пуши ---
    def _markup(self):
        if not self.webapp_url:
            return None
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Открыть лиды", web_app=WebAppInfo(url=f"{self.webapp_url}/?view=leads"))]])

    async def _send(self, chat_id: int, text: str, silent: bool = False) -> None:
        try:
            await self.bot.send_message(chat_id, text, parse_mode="HTML",
                                        reply_markup=self._markup(), disable_notification=silent)
        except Exception as e:  # бот заблокирован / не нажат /start — запрос не роняем
            log.warning("Leads push %s не доставлен: %s", chat_id, e)

    def notify_partner(self, actor_id: int, actor_name: str, lead: dict, old: str) -> None:
        text = change_text(actor_name, lead, old)

        async def run():
            for fid in self.founder_ids - {actor_id}:
                await self._send(fid, text, silent=True)

        t = asyncio.create_task(run())
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)


def setup_leads(app, *, current_user, bot, founder_ids: set[int], webapp_url: str, data_dir) -> LeadsModule:
    from fastapi import APIRouter, Depends, HTTPException
    from pydantic import BaseModel

    module = LeadsModule(bot, founder_ids, webapp_url, data_dir)
    router = APIRouter(prefix="/api/leads")

    async def founder_user(user=Depends(current_user)):
        # 404, а не 403: обычный пользователь не должен узнать, что раздел существует
        if user.id not in module.founder_ids:
            raise HTTPException(404, "Not Found")
        return user

    class StatusIn(BaseModel):
        status: str

    @router.get("/access")
    async def leads_access(user=Depends(current_user)):
        """Тихая проверка прав при старте Mini App: не-основатель получает 200 с founder=false."""
        return {"success": True, "founder": user.id in module.founder_ids}

    @router.get("")
    async def leads_list(_=Depends(founder_user)):
        leads = await asyncio.to_thread(module.store.list_leads)
        present = {l["niche"] for l in leads}
        return {
            "statuses": [{"id": k, "label": v} for k, v in STATUSES.items()],
            "niches": [{"id": k, "label": v} for k, v in NICHES.items() if k in present],
            "leads": leads,
        }

    @router.post("/{lead_id}/status")
    async def leads_set_status(lead_id: str, body: StatusIn, user=Depends(founder_user)):
        if body.status not in STATUSES:
            raise HTTPException(422, "Неизвестный статус.")
        name = (user.full_name or "").strip() or f"id{user.id}"
        res = await asyncio.to_thread(module.store.set_status, lead_id, body.status, user.id, name)
        if res is None:
            raise HTTPException(404, "Лид не найден.")
        lead, old = res
        if old != body.status:
            module.notify_partner(user.id, name, lead, old)
        return lead

    app.include_router(router)
    return module
