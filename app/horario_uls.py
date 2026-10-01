"""Lee el PDF de horario que entrega la ULS (formato fijo, generado por TCPDF).

Cada clase es una celda gris oscura; su columna da el día y las filas de bloques
que cubre (columna izquierda, también gris oscura) dan la hora de inicio y término.
"""
import io
import re

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTRect, LTTextContainer, LTTextLine

DAYS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO"]
TITLE = re.compile(r"^(.+?)\s*\[([TL])-\d+\]$")
TIME = re.compile(r"^\d{2}:\d{2}$")


def _dark(r) -> bool:
    c = r.non_stroking_color
    return isinstance(c, (tuple, list)) and len(c) == 3 and all(0.5 < v < 0.75 for v in c)


def _inside(line, x0, y0, x1, y1) -> bool:
    return x0 <= (line.x0 + line.x1) / 2 <= x1 and y0 <= (line.y0 + line.y1) / 2 <= y1


def parse(pdf: bytes) -> list[dict]:
    """→ [{"name", "kind": "T"|"L", "slots": [{"weekday", "start_time", "end_time"}]}]; [] si no es un horario ULS."""
    try:
        pages = list(extract_pages(io.BytesIO(pdf)))
    except Exception:  # cualquier archivo que no sea un PDF legible
        return []
    courses: dict[tuple[str, str], dict] = {}
    for page in pages:
        text = [(ln, ln.get_text().strip()) for box in page if isinstance(box, LTTextContainer)
                for ln in box if isinstance(ln, LTTextLine)]
        days = {t: (ln.x0 + ln.x1) / 2 for ln, t in text if t in DAYS}
        if len(days) < 5:
            continue
        cells = {(round(r.x0), round(r.y0), round(r.x1), round(r.y1)) for r in page if isinstance(r, LTRect) and _dark(r)}
        rows = []  # (y0, y1, inicio, fin) de cada bloque horario de la columna izquierda
        for x0, y0, x1, y1 in cells:
            if x1 <= 72:
                times = sorted(((ln.y0, t) for ln, t in text if TIME.match(t) and _inside(ln, x0, y0, x1, y1)), reverse=True)
                if len(times) == 2:
                    rows.append((y0, y1, times[0][1], times[1][1]))
        for x0, y0, x1, y1 in sorted(cells, key=lambda c: (-c[3], c[0])):  # de arriba abajo, de lunes a sábado
            span = sorted((r for r in rows if r[0] >= y0 - 2 and r[1] <= y1 + 2), key=lambda r: -r[1])
            title = next((m for ln, t in text if (m := TITLE.match(t)) and _inside(ln, x0, y0, x1, y1)), None)
            if x1 <= 72 or not span or not title:
                continue
            weekday = DAYS.index(min(days, key=lambda d: abs(days[d] - (x0 + x1) / 2)))
            name, kind = title[1].strip(), title[2]
            c = courses.setdefault((name, kind), {"name": name, "kind": kind, "slots": []})
            slot = {"weekday": weekday, "start_time": span[0][2], "end_time": span[-1][3]}
            if slot not in c["slots"]:
                c["slots"].append(slot)
    return list(courses.values())
