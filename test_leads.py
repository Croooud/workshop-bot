"""Тесты B2B-лидов: python -m unittest -v test_leads  (без FastAPI/aiogram)."""
import json, tempfile, threading, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from leads_api import build_digest, change_text, digest_due
from leads_store import LeadStore, detect_niche, stale_leads

SEED = Path(__file__).parent / "leads_seed.csv"
MSK = timezone(timedelta(hours=3))


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "d" / "leads.json"
        self.store = LeadStore(self.path, SEED)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed(self):
        self.assertEqual(self.store.sync_seed(), 6)
        leads = self.store.list_leads()
        self.assertEqual({l["niche"] for l in leads}, {"hookah", "anticafe", "gaming"})
        self.assertTrue(all(l["status"] == "todo" for l in leads))

    def test_reseed_keeps_statuses(self):
        self.store.sync_seed()
        lid = self.store.list_leads()[0]["id"]
        self.store.set_status(lid, "thinking", 1, "A")
        self.assertEqual(self.store.sync_seed(), 0)
        self.assertEqual(self.store.list_leads()[0]["status"], "thinking")

    def test_status_persisted_cyrillic(self):
        self.store.sync_seed()
        lid = self.store.list_leads()[1]["id"]
        lead, old = self.store.set_status(lid, "in_progress", 7, "Партнёр")
        self.assertEqual(old, "todo")
        raw = self.path.read_text(encoding="utf-8")
        self.assertIn("Партнёр", raw)
        self.assertEqual(next(l for l in json.loads(raw)["leads"] if l["id"] == lid)["status"], "in_progress")

    def test_bad_input(self):
        self.store.sync_seed()
        with self.assertRaises(ValueError):
            self.store.set_status("x", "hacked", 1, "a")
        self.assertIsNone(self.store.set_status("nope", "won", 1, "a"))

    def test_concurrent(self):
        self.store.sync_seed()
        ids = [l["id"] for l in self.store.list_leads()]
        def work(i):
            for n in range(20):
                self.store.set_status(ids[i % 6], ["todo", "won", "thinking"][n % 3], i, "u")
        ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))["leads"]), 6)
        self.assertEqual(list(self.path.parent.glob(".leads-*.tmp")), [])

    def test_corrupt_backup(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.store.sync_seed(), 6)
        self.assertEqual(len(list(self.path.parent.glob("leads.corrupt-*.json"))), 1)

    def test_meta(self):
        self.store.sync_seed()
        self.store.set_meta("last_digest", "2026-10-01")
        self.assertEqual(self.store.get_meta("last_digest"), "2026-10-01")
        self.assertEqual(len(self.store.list_leads()), 6)


class Logic(unittest.TestCase):
    def test_niche(self):
        for t, n in [("Кальянная (Премиум)", "hookah"), ("VR-клуб", "vr"), ("ПВЗ Ozon", "pvz"),
                     ("Антикафе / Лофт", "anticafe"), ("Компьютерный клуб + Lounge", "gaming")]:
            self.assertEqual(detect_niche(t), n)

    def test_stale_and_digest(self):
        now = datetime.now(timezone.utc)
        mk = lambda st, d, name="X": {"id": name + st, "name": name, "address": "<a>", "status": st,
                                      "updated_at": (now - timedelta(days=d)).isoformat()}
        leads = [mk("thinking", 4, "Мята"), mk("thinking", 1), mk("won", 30), mk("todo", 8), mk("rejected", 50)]
        self.assertEqual([l["status"] for l in stale_leads(leads, now)], ["todo", "thinking"])
        text = build_digest(leads)
        self.assertIn("Мята", text); self.assertIn("&lt;a&gt;", text); self.assertNotIn("<a>", text)  # экранирование
        self.assertIsNone(build_digest([mk("won", 99)]))

    def test_change_text_escapes(self):
        t = change_text("<b>Ив</b>", {"name": "A&B", "status": "thinking"}, "todo")
        self.assertIn("&lt;b&gt;", t); self.assertIn("A&amp;B", t)
        self.assertIn("Надо зайти", t); self.assertIn("Думают", t)

    def test_digest_due(self):
        wd = datetime(2026, 10, 1, 10, 30, tzinfo=MSK)           # четверг
        self.assertTrue(digest_due(wd, None, 10))
        self.assertFalse(digest_due(wd, "2026-10-01", 10))        # уже слали сегодня
        self.assertFalse(digest_due(wd.replace(hour=9), None, 10))  # рано
        self.assertFalse(digest_due(wd.replace(hour=22), None, 10)) # поздно: не будим на ночь
        self.assertFalse(digest_due(datetime(2026, 10, 3, 11, 0, tzinfo=MSK), None, 10))  # суббота


if __name__ == "__main__":
    unittest.main()
