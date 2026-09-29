"""Генерация PDF коммерческого предложения (сметы) ЭЛИВЕЙТ для B2B-заказов.

Дизайн по брендбуку: Deep Black #000000, Corporate Graphite #2E2E2E, Pure White, акцент Electric Blue #007BFF.
Шрифт — Inter (OFL), лежит в assets/fonts: на сервере может не быть системных шрифтов с кириллицей.

Функция build_proposal_pdf() синхронная и CPU-bound — вызывать через asyncio.to_thread().
Все цифры в смете приходят уже посчитанными сервером; тексты (в т.ч. от LLM) экранируются здесь.
"""
from __future__ import annotations

import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

# ───────────────────────── Бренд ─────────────────────────
BLACK = colors.HexColor("#000000")
GRAPHITE = colors.HexColor("#2E2E2E")
WHITE = colors.HexColor("#FFFFFF")
BLUE = colors.HexColor("#007BFF")
# Производные оттенки графита (для печати на белом листе)
MUTED = colors.HexColor("#6E6E73")
LINE = colors.HexColor("#DADADD")
ZEBRA = colors.HexColor("#F4F4F5")

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
F_REG, F_SEMI, F_BOLD = "Inter", "Inter-SemiBold", "Inter-Bold"

COMPANY = {
    "name": "Инженерный центр ЭЛИВЕЙТ",
    "phone": "+7 (991) 888-60-17",
    "telegram": "t.me/IvanMiroshnichenkoo",
}

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
HEADER_H = 38 * mm
FOOTER_H = 16 * mm

_fonts_ready = False


def _register_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    for name, file in ((F_REG, "Inter-Regular.ttf"), (F_SEMI, "Inter-SemiBold.ttf"), (F_BOLD, "Inter-Bold.ttf")):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, file)))
    pdfmetrics.registerFontFamily(F_REG, normal=F_REG, bold=F_BOLD, italic=F_REG, boldItalic=F_BOLD)
    _fonts_ready = True


def rub(v: int) -> str:
    return f"{v:,}".replace(",", " ") + " ₽"


def _t(text) -> str:
    """Экранирование для Paragraph (ReportLab разбирает мини-разметку)."""
    return escape(str(text or ""))


# ───────────────────────── Стили ─────────────────────────
def _styles():
    s = {}
    s["body"] = ParagraphStyle("body", fontName=F_REG, fontSize=9.5, leading=14, textColor=GRAPHITE)
    s["lead"] = ParagraphStyle("lead", parent=s["body"], fontSize=11, leading=16.5, textColor=BLACK)
    s["muted"] = ParagraphStyle("muted", parent=s["body"], fontSize=8, leading=11.5, textColor=MUTED)
    s["label"] = ParagraphStyle("label", fontName=F_SEMI, fontSize=7, leading=9, textColor=MUTED)
    s["value"] = ParagraphStyle("value", fontName=F_SEMI, fontSize=10, leading=13.5, textColor=BLACK)
    s["h"] = ParagraphStyle("h", fontName=F_BOLD, fontSize=13, leading=16, textColor=BLACK, spaceBefore=4, spaceAfter=8)
    s["cell"] = ParagraphStyle("cell", parent=s["body"], fontSize=9, leading=12.5)
    s["cell_b"] = ParagraphStyle("cell_b", parent=s["cell"], fontName=F_SEMI, textColor=BLACK)
    s["cell_r"] = ParagraphStyle("cell_r", parent=s["cell"], alignment=TA_RIGHT)
    s["cell_rb"] = ParagraphStyle("cell_rb", parent=s["cell_r"], fontName=F_SEMI, textColor=BLACK)
    s["th"] = ParagraphStyle("th", fontName=F_SEMI, fontSize=7.5, leading=9.5, textColor=WHITE)
    s["th_r"] = ParagraphStyle("th_r", parent=s["th"], alignment=TA_RIGHT)
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=11, bulletIndent=1, bulletFontName=F_BOLD,
                                 bulletFontSize=11, bulletColor=BLUE, spaceAfter=2)
    s["svc"] = ParagraphStyle("svc", fontName=F_SEMI, fontSize=10, leading=13, textColor=BLACK, spaceAfter=4)
    s["total_l"] = ParagraphStyle("total_l", fontName=F_SEMI, fontSize=9, leading=12, textColor=WHITE, alignment=TA_LEFT)
    s["total_v"] = ParagraphStyle("total_v", fontName=F_BOLD, fontSize=16, leading=19, textColor=WHITE, alignment=TA_RIGHT)
    return s


def _section(num: int, title: str, st) -> Table:
    """Заголовок раздела: синий номер «01 /» + название + тонкая линия."""
    p = Paragraph(f'<font color="#007BFF">{num:02d} /</font>&nbsp;&nbsp;{_t(title)}', st["h"])
    t = Table([[p]], colWidths=[PAGE_W - 2 * MARGIN_X], spaceAfter=3 * mm)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


# ───────────────────────── Холст: шапка, подвал, «стр. N из M» ─────────────────────────
class _BrandCanvas(rl_canvas.Canvas):
    """Двухпроходная нумерация страниц: подвал рисуется в save(), когда известно общее число страниц."""

    def __init__(self, *args, meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._meta = meta or {}
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self._draw_chrome(total)
            super().showPage()
        super().save()

    def _draw_chrome(self, total: int):
        m = self._meta
        page = self._pageNumber
        # Шапка: чёрная плашка + графитовая полоса + синяя акцентная линия
        self.setFillColor(BLACK)
        self.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, stroke=0, fill=1)
        self.setFillColor(GRAPHITE)
        self.rect(0, PAGE_H - HEADER_H, 62 * mm, HEADER_H, stroke=0, fill=1)
        self.setFillColor(BLUE)
        self.rect(0, PAGE_H - HEADER_H - 1.4, PAGE_W, 1.4, stroke=0, fill=1)
        self.rect(MARGIN_X, PAGE_H - 12 * mm, 3.2 * mm, 3.2 * mm, stroke=0, fill=1)  # «пиксель» бренда

        self.setFillColor(WHITE)
        self.setFont(F_BOLD, 19)
        self.drawString(MARGIN_X, PAGE_H - 22 * mm, "ЭЛИВЕЙТ")
        self.setFont(F_SEMI, 6.8)
        self.setFillColor(colors.HexColor("#A1A1A6"))
        self.drawString(MARGIN_X, PAGE_H - 27.5 * mm, "И Н Ж Е Н Е Р Н Ы Й   С Е Р В И С")

        right = PAGE_W - MARGIN_X
        self.setFillColor(BLUE)
        self.setFont(F_SEMI, 7)
        self.drawRightString(right, PAGE_H - 12.5 * mm, "К О М М Е Р Ч Е С К О Е   П Р Е Д Л О Ж Е Н И Е")
        self.setFillColor(WHITE)
        self.setFont(F_BOLD, 15)
        self.drawRightString(right, PAGE_H - 21 * mm, m.get("number", ""))
        self.setFont(F_REG, 8.5)
        self.setFillColor(colors.HexColor("#C7C7CC"))
        self.drawRightString(right, PAGE_H - 27.5 * mm, f"от {m.get('date', '')} · действует {m.get('valid_days', 14)} дней")

        # Подвал
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, FOOTER_H, PAGE_W - MARGIN_X, FOOTER_H)
        self.setFont(F_REG, 7.5)
        self.setFillColor(MUTED)
        self.drawString(MARGIN_X, FOOTER_H - 5 * mm,
                        f"{COMPANY['name']}  ·  {COMPANY['phone']}  ·  {COMPANY['telegram']}")
        self.setFont(F_SEMI, 7.5)
        self.setFillColor(GRAPHITE)
        self.drawRightString(PAGE_W - MARGIN_X, FOOTER_H - 5 * mm, f"{page} / {total}")


# ───────────────────────── Сборка документа ─────────────────────────
def build_proposal_pdf(data: dict) -> bytes:
    """data:
    number, date, valid_days,
    client: {name, phone, username}, office_info, workplaces, order_id, order_date,
    lines: [{name, unit, qty, price, total, note}], total, has_negotiable,
    content: {summary, scope: [{service, work: [..]}], stages: [{title, duration, result}], recommendations: [..]}
    """
    _register_fonts()
    st = _styles()
    buf = io.BytesIO()
    content_w = PAGE_W - 2 * MARGIN_X

    doc = BaseDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X,
        topMargin=HEADER_H + 10 * mm, bottomMargin=FOOTER_H + 8 * mm,
        title=f"Коммерческое предложение {data.get('number', '')}", author="ЭЛИВЕЙТ",
        subject="Предварительная смета", creator="ЭЛИВЕЙТ CRM",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="brand", frames=[frame])])

    c = data.get("content") or {}
    client = data.get("client") or {}
    story = []

    # ── Реквизиты: заказчик / объект / заявка
    def kv(label, value):
        return [Paragraph(_t(label).upper(), st["label"]), Spacer(1, 2), Paragraph(_t(value) or "—", st["value"])]

    contact = " · ".join(x for x in (client.get("phone"), f"@{client['username']}" if client.get("username") else None) if x)
    wp = data.get("workplaces")
    info = Table([[
        kv("Заказчик", client.get("name") or "Клиент") + [Spacer(1, 2), Paragraph(_t(contact), st["muted"])],
        kv("Объект", data.get("office_info") or "Уточняется") + [Spacer(1, 2), Paragraph(
            _t(f"Рабочих мест: {wp}" if wp else "Количество рабочих мест уточняется"), st["muted"])],
        kv("Заявка", data.get("order_id")) + [Spacer(1, 2), Paragraph(_t(f"от {data.get('order_date', '')}"), st["muted"])],
    ]], colWidths=[content_w * 0.38, content_w * 0.38, content_w * 0.24])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
        ("LINEBEFORE", (0, 0), (0, 0), 2.2, BLUE),
        ("LINEBEFORE", (1, 0), (-1, 0), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story += [info, Spacer(1, 8 * mm)]

    # ── 01 Задача
    n = 1
    if c.get("summary"):
        story += [_section(n, "Задача и решение", st), Paragraph(_t(c["summary"]), st["lead"]), Spacer(1, 7 * mm)]
        n += 1

    # ── 02 Смета
    header = [Paragraph("№", st["th"]), Paragraph("УСЛУГА", st["th"]), Paragraph("ЕД.", st["th"]),
              Paragraph("КОЛ-ВО", st["th_r"]), Paragraph("ЦЕНА", st["th_r"]), Paragraph("СУММА", st["th_r"])]
    rows = [header]
    for i, ln in enumerate(data.get("lines") or [], 1):
        priced = ln.get("price", 0) > 0
        name = f"{_t(ln['name'])}"
        if ln.get("note"):
            name += f'<br/><font size="7.5" color="#6E6E73">{_t(ln["note"])}</font>'
        rows.append([
            Paragraph(f"{i:02d}", st["cell"]),
            Paragraph(name, st["cell_b"]),
            Paragraph(_t(ln.get("unit") or "услуга"), st["cell"]),
            Paragraph(str(ln.get("qty", 1)), st["cell_r"]),
            Paragraph(("от " + rub(ln["price"])) if priced else "—", st["cell_r"]),
            Paragraph(rub(ln["total"]) if priced else _t(ln.get("price_label") or "По договорённости"), st["cell_rb"]),
        ])
    table = Table(rows, colWidths=[9 * mm, content_w - 9 * mm - 17 * mm - 16 * mm - 28 * mm - 32 * mm,
                                   17 * mm, 16 * mm, 28 * mm, 32 * mm], repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), GRAPHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 7), ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 8), ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
    ]
    for r in range(2, len(rows), 2):
        ts.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    table.setStyle(TableStyle(ts))

    total = data.get("total", 0)
    total_label = ("ИТОГО, ОТ" if total else "ИТОГО")
    total_value = rub(total) if total else "Индивидуальный расчёт"
    tot = Table([[Paragraph(total_label, st["total_l"]), Paragraph(total_value, st["total_v"])]],
                colWidths=[content_w * 0.5, content_w * 0.5])
    tot.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLACK),
        ("LINEABOVE", (0, 0), (-1, 0), 2, BLUE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    note = "Цены указаны в рублях по действующему прайсу ЭЛИВЕЙТ и являются нижней границей стоимости."
    if data.get("has_negotiable"):
        note += " Позиции «по договорённости» рассчитываются после аудита и в итог не включены."
    story += [CondPageBreak(60 * mm), _section(n, "Предварительная смета", st), table, tot, Spacer(1, 2.5 * mm),
              Paragraph(_t(note), st["muted"]), Spacer(1, 7 * mm)]
    n += 1

    # ── 03 Состав работ
    scope = [s for s in (c.get("scope") or []) if s.get("work")]
    if scope:
        story += [CondPageBreak(40 * mm), _section(n, "Состав работ", st)]
        for s in scope:
            block = [Paragraph(_t(s["service"]), st["svc"])]
            block += [Paragraph(_t(w), st["bullet"], bulletText="•") for w in s["work"]]
            block.append(Spacer(1, 4 * mm))
            story.append(KeepTogether(block))
        story.append(Spacer(1, 3 * mm))
        n += 1

    # ── 04 Этапы и сроки
    stages = c.get("stages") or []
    if stages:
        srows = [[Paragraph("ЭТАП", st["th"]), Paragraph("СРОК", st["th"]), Paragraph("РЕЗУЛЬТАТ", st["th"])]]
        for i, sg in enumerate(stages, 1):
            srows.append([
                Paragraph(f'<font color="#007BFF">{i:02d}</font>&nbsp;&nbsp;{_t(sg.get("title"))}', st["cell_b"]),
                Paragraph(_t(sg.get("duration")), st["cell"]),
                Paragraph(_t(sg.get("result")), st["cell"]),
            ])
        stt = Table(srows, colWidths=[content_w * 0.34, content_w * 0.16, content_w * 0.50], repeatRows=1)
        sts = [
            ("BACKGROUND", (0, 0), (-1, 0), GRAPHITE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE),
        ]
        for r in range(2, len(srows), 2):
            sts.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
        stt.setStyle(TableStyle(sts))
        story += [CondPageBreak(45 * mm), _section(n, "Этапы и сроки", st), stt, Spacer(1, 7 * mm)]
        n += 1

    # ── 05 Рекомендации
    recs = c.get("recommendations") or []
    if recs:
        story += [CondPageBreak(35 * mm), _section(n, "Рекомендации инженера", st)]
        story += [Paragraph(_t(r), st["bullet"], bulletText="•") for r in recs]
        story.append(Spacer(1, 7 * mm))
        n += 1

    # ── 06 Условия
    terms = [
        f"Предложение действует {data.get('valid_days', 14)} дней с даты формирования.",
        "Смета предварительная: окончательная стоимость и сроки фиксируются в договоре после выезда инженера и аудита.",
        "Стоимость оборудования, комплектующих и лицензий ПО в смету не входит и согласуется отдельно.",
    ]
    story += [CondPageBreak(40 * mm), _section(n, "Условия", st)]
    story += [Paragraph(_t(t), st["bullet"], bulletText="•") for t in terms]
    story += [Spacer(1, 8 * mm)]

    sign = Table([[
        [Paragraph("ГОТОВЫ ОБСУДИТЬ ДЕТАЛИ", st["label"]), Spacer(1, 3),
         Paragraph(_t(COMPANY["name"]), st["value"]),
         Paragraph(_t(f"{COMPANY['phone']}  ·  {COMPANY['telegram']}"), st["body"])],
    ]], colWidths=[content_w])
    sign.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, 0), 2.2, BLUE),
        ("BACKGROUND", (0, 0), (-1, -1), ZEBRA),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(KeepTogether([sign]))

    meta = {"number": data.get("number", ""), "date": data.get("date", ""), "valid_days": data.get("valid_days", 14)}
    doc.build(story, canvasmaker=lambda *a, **k: _BrandCanvas(*a, meta=meta, **k))
    return buf.getvalue()
