"""Cálculo de asistencia. Funciones puras, sin DB."""
from dataclasses import dataclass, field
from functools import cached_property
from datetime import date, timedelta


@dataclass(frozen=True)
class Course:
    id: int
    name: str
    kind: str
    min_pct: int


@dataclass(frozen=True)
class Slot:
    id: int
    course_id: int
    weekday: int


@dataclass
class Plan:
    start: date
    end: date
    off: set[date]
    courses: list[Course]
    slots: list[Slot]
    absences: set[tuple[int, date]] = field(default_factory=set)  # (slot_id, date)
    moves: set[tuple[int, date, date]] = field(default_factory=set)  # recuperaciones: (course_id, día original, día en que se hizo)

    @cached_property
    def dates(self) -> dict[int, set[date]]:
        """Días con clase de cada bloque: su día de la semana sin feriados, con las recuperaciones aplicadas."""
        out = {}
        for s in self.slots:
            moved = [(o, n) for c, o, n in self.moves if c == s.course_id]
            gone = {o for o, _ in moved}
            out[s.id] = {d for d in class_dates(self, s.weekday) if d not in gone} | {n for o, n in moved if o.weekday() == s.weekday}
        return out


def _days(p: Plan):
    return (p.start + timedelta(i) for i in range((p.end - p.start).days + 1))


def class_dates(p: Plan, weekday: int) -> list[date]:
    return [d for d in _days(p) if d.weekday() == weekday and d not in p.off]


def _stats(p: Plan, today: date) -> dict[int, dict]:
    by_id = {s.id: s for s in p.slots}
    out = {}
    for c in p.courses:
        slots = [s for s in p.slots if s.course_id == c.id]
        total = sum(len(p.dates[s.id]) for s in slots)
        minimo = (c.min_pct * total + 99) // 100
        valid = [d for sid, d in p.absences
                 if sid in by_id and by_id[sid].course_id == c.id and d in p.dates[sid]]
        reales = sum(d <= today for d in valid)
        planeadas = len(valid) - reales
        quedan = total - minimo - len(valid)
        dictadas = sum(d <= today for s in slots for d in p.dates[s.id])
        restantes = total - dictadas
        # clases por delante que aún no marca como falta; si va a las primeras k, después puede faltar al resto
        proximas = sorted(d for s in slots for d in p.dates[s.id] if d > today and (s.id, d) not in p.absences)
        k = len(proximas) - quedan
        ir_seguido = ({"clases": k, "hasta": proximas[k - 1].isoformat(), "luego": len(proximas) - k}
                      if 0 < k < len(proximas) else None)
        out[c.id] = dict(id=c.id, name=c.name, kind=c.kind, min_pct=c.min_pct, total=total, minimo=minimo,
                         permitidas=total - minimo, reales=reales, planeadas=planeadas, quedan=quedan,
                         dictadas=dictadas, restantes=restantes,
                         # aunque falte a todas las que quedan (y no tiene ya planeadas), cumple el mínimo
                         faltar_todo=restantes > 0 and quedan >= restantes - planeadas, ir_seguido=ir_seguido)
    return out


def _day_color(p: Plan, d: date, today: date, stats: dict[int, dict]) -> str:
    slots = [s for s in p.slots if d in p.dates[s.id]]
    if not slots:
        return "gris"
    pending = [s for s in slots if (s.id, d) not in p.absences]
    if not pending:
        return "falta"
    if d < today:
        return "asistio"
    cost: dict[int, int] = {}
    for s in pending:
        cost[s.course_id] = cost.get(s.course_id, 0) + 1
    r = min(stats[cid]["quedan"] - n for cid, n in cost.items())
    return "rojo" if r < 0 else "amarillo" if r == 0 else "verde"


def day_color(p: Plan, d: date, today: date) -> str:
    return _day_color(p, d, today, _stats(p, today))


def summarize(p: Plan, today: date) -> dict:
    stats = _stats(p, today)
    weekdays = {}
    for w in sorted({s.weekday for s in p.slots}):
        per_course: dict[int, int] = {}
        for s in p.slots:
            if s.weekday == w:
                per_course[s.course_id] = per_course.get(s.course_id, 0) + 1
        n = min(stats[cid]["quedan"] // k for cid, k in per_course.items())
        wslots = [s for s in p.slots if s.weekday == w]
        left = sum(1 for d in class_dates(p, w)
                   if d >= today and any((s.id, d) not in p.absences for s in wslots))
        weekdays[w] = max(0, min(n, left))
    class_days = sorted({d for ds in p.dates.values() for d in ds})
    # semestre: si todos los ramos con clases por delante tienen salida, manda el que pide ir hasta más tarde
    pending = [c for c in stats.values() if c["restantes"] > c["planeadas"]]
    plans = [c["ir_seguido"] for c in pending if c["ir_seguido"]]
    hasta = max((x["hasta"] for x in plans), default=None)
    ir_seguido = ({"dias": sum(today < d <= date.fromisoformat(hasta) for d in class_days), "hasta": hasta}
                  if plans and all(c["faltar_todo"] or c["ir_seguido"] for c in pending) else None)
    return {
        "courses": list(stats.values()),
        "weekdays": weekdays,
        "days": {"total": len(class_days), "done": sum(d <= today for d in class_days)},
        "ir_seguido": ir_seguido,
        "calendar": {d.isoformat(): _day_color(p, d, today, stats) for d in _days(p)},
    }
