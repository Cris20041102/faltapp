from datetime import date, timedelta

from app.calc import Course, Plan, Slot, day_color, summarize


def uls():
    off = {date(2026, 9, 14) + timedelta(i) for i in range(5)} | {date(2026, 10, 9), date(2026, 10, 12)}
    courses = [Course(i, n, k, p) for i, (n, k, p) in enumerate(
        [("EP", "T", 60), ("PAT", "T", 60), ("PAL", "L", 70), ("SIT", "T", 60),
         ("SIL", "L", 70), ("BDT", "T", 60), ("BDL", "L", 70), ("SOC", "T", 60)], 1)]
    slots = [Slot(1, 1, 0), Slot(2, 1, 4), Slot(3, 2, 0), Slot(4, 2, 1), Slot(5, 3, 1), Slot(6, 4, 0),
             Slot(7, 4, 1), Slot(8, 5, 0), Slot(9, 6, 1), Slot(10, 6, 3), Slot(11, 7, 2), Slot(12, 8, 0),
             Slot(13, 8, 4)]
    return Plan(date(2026, 8, 10), date(2026, 12, 4), off, courses, slots, set())


def test_totales_uls():
    s = summarize(uls(), date(2026, 8, 1))
    got = {c["name"]: (c["total"], c["minimo"], c["permitidas"]) for c in s["courses"]}
    assert got == {"EP": (30, 18, 12), "PAT": (31, 19, 12), "PAL": (16, 12, 4), "SIT": (31, 19, 12),
                   "SIL": (15, 11, 4), "BDT": (32, 20, 12), "BDL": (16, 12, 4), "SOC": (30, 18, 12)}
    assert s["weekdays"] == {0: 4, 1: 4, 2: 4, 3: 12, 4: 12}


def test_faltas_reales_cristian():
    p = uls()
    p.absences |= {(6, date(2026, 8, 17)), (5, date(2026, 8, 18)), (12, date(2026, 8, 24)),
                   (13, date(2026, 8, 28)), (2, date(2026, 8, 21))}
    s = summarize(p, date(2026, 9, 29))
    q = {c["name"]: c["quedan"] for c in s["courses"]}
    assert q["SOC"] == 10 and q["EP"] == 11 and q["PAL"] == 3 and q["SIT"] == 11
    assert s["weekdays"] == {0: 4, 1: 3, 2: 4, 3: 10, 4: 9}


def test_real_vs_planeada():
    p = uls()
    p.absences.add((10, date(2026, 10, 1)))
    bdt = lambda t: next(c for c in summarize(p, t)["courses"] if c["name"] == "BDT")
    assert (bdt(date(2026, 9, 29))["reales"], bdt(date(2026, 9, 29))["planeadas"]) == (0, 1)
    assert (bdt(date(2026, 10, 2))["reales"], bdt(date(2026, 10, 2))["planeadas"]) == (1, 0)


def test_falta_en_dia_sin_clase_no_cuenta():
    p = uls()
    p.absences |= {(3, date(2026, 10, 12)), (1, date(2026, 9, 14)), (10, date(2026, 10, 12))}
    s = summarize(p, date(2026, 12, 31))
    assert all(c["reales"] == 0 and c["planeadas"] == 0 for c in s["courses"])


def test_semaforo():
    p, t = uls(), date(2026, 9, 29)
    assert day_color(p, date(2026, 10, 3), t) == "gris"
    assert day_color(p, date(2026, 10, 12), t) == "gris"
    assert day_color(p, date(2026, 8, 12), t) == "asistio"
    assert day_color(p, date(2026, 10, 1), t) == "verde"
    p.absences |= {(11, date(2026, 10, 7))}
    assert day_color(p, date(2026, 10, 7), t) == "falta"
    p.absences |= {(5, date(2026, 10, 13)), (5, date(2026, 10, 20)), (5, date(2026, 10, 27))}
    assert day_color(p, date(2026, 11, 3), t) == "amarillo"
    p.absences |= {(5, date(2026, 11, 3))}
    assert day_color(p, date(2026, 11, 10), t) == "rojo"


def test_calendar_cubre_todo_el_semestre():
    cal = summarize(uls(), date(2026, 9, 29))["calendar"]
    assert cal["2026-08-10"] == "asistio" and cal["2026-12-04"] == "verde" and len(cal) == 117
