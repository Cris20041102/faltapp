"""Cálculo de asistencia. Funciones puras, sin DB."""
from dataclasses import dataclass, field
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


def _days(p: Plan):
    return (p.start + timedelta(i) for i in range((p.end - p.start).days + 1))


def class_dates(p: Plan, weekday: int) -> list[date]:
    return [d for d in _days(p) if d.weekday() == weekday and d not in p.off]


def _is_class(p: Plan, slot: Slot, d: date) -> bool:
    return p.start <= d <= p.end and d.weekday() == slot.weekday and d not in p.off


def _stats(p: Plan, today: date) -> dict[int, dict]:
    by_id = {s.id: s for s in p.slots}
    out = {}
    for c in p.courses:
        slots = [s for s in p.slots if s.course_id == c.id]
        total = sum(len(class_dates(p, s.weekday)) for s in slots)
        minimo = (c.min_pct * total + 99) // 100
        valid = [d for sid, d in p.absences
                 if sid in by_id and by_id[sid].course_id == c.id and _is_class(p, by_id[sid], d)]
        reales = sum(d <= today for d in valid)
        planeadas = len(valid) - reales
        out[c.id] = dict(id=c.id, name=c.name, kind=c.kind, min_pct=c.min_pct, total=total, minimo=minimo,
                         permitidas=total - minimo, reales=reales, planeadas=planeadas,
                         quedan=total - minimo - len(valid))
    return out


def _day_color(p: Plan, d: date, today: date, stats: dict[int, dict]) -> str:
    slots = [s for s in p.slots if _is_class(p, s, d)]
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
    return {
        "courses": list(stats.values()),
        "weekdays": weekdays,
        "calendar": {d.isoformat(): _day_color(p, d, today, stats) for d in _days(p)},
    }
