"""Lee el PDF de horario que entrega la ULS (formato fijo, generado por TCPDF).

Cada clase es una celda gris oscura; su columna da el día y las filas de bloques
que cubre (columna izquierda, también gris oscura) dan la hora de inicio y término.

Tope de horario: la ULS escribe los dos títulos encima, en la misma celda (y dibuja la
2ª celda corrida hacia abajo). Por eso el texto se lee en el orden en que viene en el PDF
—así los títulos encimados no se mezclan— y cada título busca la celda que lo contiene.
"""
import io
import re

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LTChar, LTRect
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage

DAYS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"]
TITLE = re.compile(r"^(.+?)\s*\[([TL])-\d+\]$")
TIME = re.compile(r"^\d{2}:\d{2}$")


def _dark(r) -> bool:
    c = r.non_stroking_color
    return isinstance(c, (tuple, list)) and len(c) == 3 and all(0.5 < v < 0.75 for v in c)


def _pages(pdf: bytes):
    """→ por página: ([(texto, x, y)], celdas oscuras). Textos = letras seguidas en el orden del PDF."""
    rm = PDFResourceManager()
    dev = PDFPageAggregator(rm, laparams=None)  # sin análisis de diseño: respeta el orden del PDF
    it = PDFPageInterpreter(rm, dev)
    for page in PDFPage.get_pages(io.BytesIO(pdf)):
        it.process_page(page)
        lay = dev.get_result()
        runs, prev = [], None  # [texto, x0, y0, x1, y1]
        for ch in lay:
            if not isinstance(ch, LTChar):
                continue
            if prev and abs(ch.y0 - prev.y0) <= 1 and prev.x0 < ch.x0 <= prev.x1 + 6:
                r = runs[-1]
                r[0] += ch.get_text()
                r[3], r[4] = ch.x1, max(r[4], ch.y1)
            else:
                runs.append([ch.get_text(), ch.x0, ch.y0, ch.x1, ch.y1])
            prev = ch
        text = [(t.strip(), (x0 + x1) / 2, (y0 + y1) / 2) for t, x0, y0, x1, y1 in runs if t.strip()]
        cells = {(round(r.x0), round(r.y0), round(r.x1), round(r.y1)) for r in lay if isinstance(r, LTRect) and _dark(r)}
        yield text, cells


def _inside(x, y, cell) -> bool:
    x0, y0, x1, y1 = cell
    return x0 <= x <= x1 and y0 <= y <= y1


def parse(pdf: bytes) -> list[dict]:
    """→ [{"name", "kind": "T"|"L", "slots": [{"weekday", "start_time", "end_time"}]}]; [] si no es un horario ULS."""
    try:
        pages = list(_pages(pdf))
    except Exception:  # cualquier archivo que no sea un PDF legible
        return []
    courses: dict[tuple[str, str], dict] = {}
    for text, cells in pages:
        days = {t: x for t, x, _ in text if t in DAYS}
        if len(days) < 5:
            continue
        rows = []  # (y0, y1, inicio, fin) de cada bloque horario de la columna izquierda
        for cell in cells:
            if cell[2] <= 72:
                times = sorted(((y, t) for t, x, y in text if TIME.match(t) and _inside(x, y, cell)), reverse=True)
                if len(times) == 2:
                    rows.append((cell[1], cell[3], times[0][1], times[1][1]))
        span = lambda c: sorted((r for r in rows if r[0] >= c[1] - 2 and r[1] <= c[3] + 2), key=lambda r: -r[1])
        for t, x, y in text:
            title = TITLE.match(t)
            # la celda de la clase: contiene el título y cubre bloques horarios (la celda corrida de un tope queda bajo el título)
            cell = min((c for c in cells if c[2] > 72 and _inside(x, y, c) and span(c)),
                       key=lambda c: abs((c[1] + c[3]) / 2 - y), default=None)
            if not title or not cell:
                continue
            weekday = DAYS.index(min(days, key=lambda d: abs(days[d] - (cell[0] + cell[2]) / 2)))
            name, kind, rs = title[1].strip(), title[2], span(cell)
            c = courses.setdefault((name, kind), {"name": name, "kind": kind, "slots": []})
            slot = {"weekday": weekday, "start_time": rs[0][2], "end_time": rs[-1][3]}
            if slot not in c["slots"]:
                c["slots"].append(slot)
    return list(courses.values())
