"""
Хранилище B2B-лидов «Эливейт»: только стандартная библиотека.
  * LeadStore   — JSON-файл с лидами (атомарная запись, блокировка)
  * stale_leads — какие лиды пора «пнуть» пушем
Авторизацию (initData) делает bot.py — здесь её нет намеренно.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Справочники
# --------------------------------------------------------------------------- #

# порядок = порядок кнопок в интерфейсе
STATUSES: dict[str, str] = {
    "todo": "Надо зайти",
    "in_progress": "Взят в работу",
    "thinking": "Думают",
    "won": "Договорились",
    "rejected": "Отказ",
}
DEFAULT_STATUS = "todo"

NICHES: dict[str, str] = {
    "vr": "VR-клубы",
    "pvz": "ПВЗ",
    "hookah": "Кальянные",
    "anticafe": "Антикафе",
    "gaming": "Компклубы",
    "other": "Другое",
}

# Через сколько дней без движения лид попадает в пуш-напоминание.
STALE_DAYS: dict[str, int] = {"thinking": 3, "in_progress": 3, "todo": 7}


def detect_niche(type_text: str) -> str:
    s = (type_text or "").lower()
    if "кальян" in s:
        return "hookah"
    if "vr" in s or "вр-" in s:
        return "vr"
    if "пвз" in s or "пункт выдачи" in s:
        return "pvz"
    if "антикафе" in s or "тайм-кафе" in s or "лофт" in s:
        return "anticafe"
    if "компьютер" in s:
        return "gaming"
    return "other"


def lead_id(name: str, address: str) -> str:
    """Стабильный id: при повторном импорте CSV статусы не теряются."""
    raw = f"{name.strip().lower()}|{address.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Хранилище
# --------------------------------------------------------------------------- #

class LeadStore:
    """
    leads.json: {"version": 1, "meta": {...}, "leads": [...]}
    Рассчитано на ОДИН процесс uvicorn (как на Render по умолчанию):
    threading.Lock защищает read-modify-write, запись атомарная (tmp + os.replace).
    """

    def __init__(self, path: str | os.PathLike, seed_csv: str | os.PathLike | None = None):
        self.path = Path(path)
        self.seed_csv = Path(seed_csv) if seed_csv else None
        self._lock = threading.Lock()

    # ---- низкий уровень ---------------------------------------------------- #
    def _empty(self) -> dict:
        return {"version": 1, "meta": {}, "leads": []}

    def _read(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict) or not isinstance(doc.get("leads"), list):
                raise ValueError("bad structure")
            doc.setdefault("meta", {})
            return doc
        except (json.JSONDecodeError, ValueError):
            # Битый файл не затираем молча — откладываем копию и начинаем с чистого.
            backup = self.path.with_suffix(f".corrupt-{int(datetime.now().timestamp())}.json")
            self.path.rename(backup)
            return self._empty()

    def _write(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".leads-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)  # атомарно
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---- импорт CSV -------------------------------------------------------- #
    def _parse_csv(self) -> list[dict]:
        if not self.seed_csv or not self.seed_csv.exists():
            return []
        out: list[dict] = []
        with open(self.seed_csv, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        for row in rows[1:]:  # пропускаем заголовок; колонки берём по позиции
            if len(row) < 5 or not row[1].strip():
                continue
            typ, name, addr, pain, script = (c.strip() for c in row[:5])
            out.append({
                "id": lead_id(name, addr),
                "niche": detect_niche(typ),
                "type": typ,
                "name": name,
                "address": addr,
                "pain": pain,
                "script": script,
                "status": DEFAULT_STATUS,
                "updated_at": now_iso(),
                "updated_by": None,
            })
        return out

    def sync_seed(self) -> int:
        """Добавляет из CSV только новые лиды; существующие (и их статусы) не трогает."""
        with self._lock:
            doc = self._read()
            known = {l["id"] for l in doc["leads"]}
            new = [l for l in self._parse_csv() if l["id"] not in known]
            if new or not self.path.exists():
                doc["leads"].extend(new)
                self._write(doc)
            return len(new)

    # ---- публичное API ----------------------------------------------------- #
    def list_leads(self) -> list[dict]:
        with self._lock:
            return self._read()["leads"]

    def set_status(self, lid: str, status: str, user_id: int, user_name: str) -> tuple[dict, str] | None:
        """Возвращает (лид, прежний_статус) или None, если лида нет."""
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        with self._lock:
            doc = self._read()
            for lead in doc["leads"]:
                if lead["id"] == lid:
                    old = lead["status"]
                    lead["status"] = status
                    lead["updated_at"] = now_iso()
                    lead["updated_by"] = {"id": user_id, "name": user_name}
                    self._write(doc)
                    return lead, old
            return None

    def get_meta(self, key: str, default=None):
        with self._lock:
            return self._read()["meta"].get(key, default)

    def set_meta(self, key: str, value) -> None:
        with self._lock:
            doc = self._read()
            doc["meta"][key] = value
            self._write(doc)


# --------------------------------------------------------------------------- #
# Напоминания
# --------------------------------------------------------------------------- #

def stale_leads(leads: list[dict], now: datetime | None = None,
                stale_days: dict[str, int] = STALE_DAYS) -> list[dict]:
    """Лиды, по которым давно нет движения. Самые «застарелые» — первыми."""
    now = now or datetime.now(timezone.utc)
    out = []
    for l in leads:
        limit = stale_days.get(l["status"])
        if limit is None:
            continue
        try:
            changed = datetime.fromisoformat(l["updated_at"])
        except (KeyError, ValueError):
            continue
        age = now - changed
        if age >= timedelta(days=limit):
            out.append({**l, "_age_days": age.days})
    out.sort(key=lambda x: x["_age_days"], reverse=True)
    return out
