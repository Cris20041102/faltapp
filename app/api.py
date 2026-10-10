import datetime as dt
import hmac
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, hash_password, make_token, verify_password
from app.horario_uls import parse as parse_horario_uls
from app import calc, push
from app.db import get_db
from app.models import Absence, Course, Event, Friendship, Makeup, NoClassDay, Proposal, ProposalMember, PushSubscription, Semester, Slot, User

router = APIRouter(prefix="/api")


def user_out(u: User) -> dict:
    avatar = f"/api/users/{u.id}/avatar?v={u.avatar_version}" if u.avatar_type else None
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "avatar_url": avatar}


def profile_out(u: User) -> dict:
    return user_out(u) | {"bio": u.bio, "career": u.career, "year": u.year, "status": u.status, "banner_color": u.banner_color}


def now() -> datetime:
    return datetime.now(timezone.utc)


def next_change(changed_at: datetime | None, days: int) -> datetime | None:
    """Fecha desde la que se puede volver a cambiar, o None si ya se puede."""
    if not changed_at:
        return None
    t = (changed_at if changed_at.tzinfo else changed_at.replace(tzinfo=timezone.utc)) + timedelta(days=days)
    return t if t > now() else None


USERNAME_DAYS, NAME_DAYS = 30, 14


def me_out(u: User) -> dict:
    nxt = lambda at, days: (n := next_change(at, days)) and n.isoformat()
    return profile_out(u) | {"username_next_change": nxt(u.username_changed_at, USERNAME_DAYS),
                             "display_name_next_change": nxt(u.display_name_changed_at, NAME_DAYS)}


def check_username(v: str) -> str:
    v = v.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.]{3,30}", v):
        raise ValueError("El usuario debe tener de 3 a 30 caracteres: letras, números, punto o guion bajo")
    return v


# ---------- auth ----------
class Credentials(BaseModel):
    username: str
    password: str = Field(max_length=100)

    @field_validator("username")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().lower()


class Register(Credentials):
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        return check_username(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("La contraseña debe tener al menos 6 caracteres")
        return v


@router.post("/auth/register")
def register(body: Register, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Ese usuario ya existe")
    u = User(username=body.username, display_name=body.display_name.strip(), password_hash=hash_password(body.password))
    db.add(u)
    db.commit()
    return {"token": make_token(u.id)}


@router.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    return {"token": make_token(u.id)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return me_out(user)


# ---------- perfil ----------
class ProfilePatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=60)
    username: str | None = None
    bio: str | None = Field(None, max_length=160)
    career: str | None = Field(None, max_length=60)
    year: int | None = Field(None, ge=1, le=7)
    status: str | None = Field(None, max_length=60)
    banner_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("username")
    @classmethod
    def _username(cls, v: str | None) -> str | None:
        return v if v is None else check_username(v)


@router.patch("/me")
def patch_me(body: ProfilePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "display_name" in data:
        data["display_name"] = data["display_name"].strip()
    for field, days, label in (("username", USERNAME_DAYS, "tu @"), ("display_name", NAME_DAYS, "tu nombre")):
        if field not in data:
            continue
        if data[field] == getattr(user, field):
            data.pop(field)
            continue
        if nxt := next_change(getattr(user, f"{field}_changed_at"), days):
            raise HTTPException(400, f"Podrás cambiar {label} el {nxt:%d/%m}")
        setattr(user, f"{field}_changed_at", now())
    if "username" in data and db.scalar(select(User.id).where(User.username == data["username"], User.id != user.id)):
        raise HTTPException(409, "Ese usuario ya existe")
    for k, v in data.items():
        setattr(user, k, v)
    db.commit()
    return me_out(user)


AVATAR_MAX = 2_000_000


def image_type(b: bytes) -> str | None:
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if b.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return None  # SVG y otros formatos no: podrían traer scripts


@router.put("/me/avatar")
async def put_avatar(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if int(request.headers.get("content-length") or 0) > AVATAR_MAX:
        raise HTTPException(413, "La imagen pesa más de 2 MB")
    data = await request.body()
    if len(data) > AVATAR_MAX:
        raise HTTPException(413, "La imagen pesa más de 2 MB")
    if not (kind := image_type(data)):
        raise HTTPException(400, "Sube una imagen PNG, JPG, WEBP o GIF")
    user.avatar, user.avatar_type, user.avatar_version = data, kind, user.avatar_version + 1
    db.commit()
    return me_out(user)


@router.delete("/me/avatar", status_code=204)
def delete_avatar(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.avatar, user.avatar_type, user.avatar_version = None, None, user.avatar_version + 1
    db.commit()
    return Response(status_code=204)


@router.get("/users/{id}/avatar")
def get_avatar(id: int, db: Session = Depends(get_db)):  # pública: las etiquetas <img> no mandan token
    u = db.get(User, id)
    if not u or not u.avatar_type:
        raise HTTPException(404, "No encontrado")
    return Response(u.avatar, media_type=u.avatar_type,
                    headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})




# ---------- helpers ----------
def get_owned(db: Session, model, id: int, user: User):
    """Semester/Event tienen user_id; NoClassDay/Course cuelgan de un semestre."""
    obj = db.get(model, id)
    owner = obj and (getattr(obj, "user_id", None) or db.get(Semester, obj.semester_id).user_id)
    if owner != user.id:
        raise HTTPException(404, "No encontrado")
    return obj


def active_semester(db: Session, user: User) -> Semester | None:
    return db.scalar(select(Semester).where(Semester.user_id == user.id, Semester.active))


def fetch_holidays(country: str, years: list[int]) -> list[tuple[date, str]] | None:
    if os.environ.get("FALTAPP_NO_HOLIDAYS"):
        return None
    out = []
    try:
        for y in years:
            r = httpx.get(f"https://date.nager.at/api/v3/PublicHolidays/{y}/{country}", timeout=5)
            r.raise_for_status()
            out += [(date.fromisoformat(h["date"]), h["localName"]) for h in r.json()]
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return out


def slot_out(s: Slot) -> dict:
    return {"id": s.id, "weekday": s.weekday, "start_time": s.start_time.strftime("%H:%M"), "end_time": s.end_time.strftime("%H:%M")}


def course_out(c: Course) -> dict:
    return {"id": c.id, "name": c.name, "kind": c.kind, "min_pct": c.min_pct, "slots": [slot_out(s) for s in c.slots],
            "makeups": [{"id": m.id, "original": m.original, "date": m.date} for m in c.makeups], "grades": c.grades}


def semester_out(s: Semester, full: bool = False) -> dict:
    out = {"id": s.id, "name": s.name, "start_date": s.start_date, "end_date": s.end_date,
           "country_code": s.country_code, "active": s.active}
    if full:
        out["no_class_days"] = [{"id": d.id, "date": d.date, "reason": d.reason} for d in s.no_class_days]
        out["courses"] = [course_out(c) for c in s.courses]
    return out


# ---------- semestres ----------
class SemesterIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    start_date: date
    end_date: date
    country_code: str = Field(pattern=r"^[A-Za-z]{2}$")

    @model_validator(mode="after")
    def _rango(self):
        if self.start_date >= self.end_date:
            raise ValueError("La fecha de inicio debe ser anterior a la de término")
        return self


class SemesterPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    active: bool | None = None


@router.get("/semesters")
def list_semesters(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [semester_out(s) for s in db.scalars(select(Semester).where(Semester.user_id == user.id).order_by(Semester.start_date))]


@router.post("/semesters")
def create_semester(body: SemesterIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Semester).where(Semester.user_id == user.id).values(active=False))
    s = Semester(user_id=user.id, active=True, **body.model_dump() | {"country_code": body.country_code.upper()})
    hol = fetch_holidays(s.country_code, list(range(s.start_date.year, s.end_date.year + 1)))
    for d, reason in {d: r for d, r in (hol or []) if s.start_date <= d <= s.end_date}.items():
        s.no_class_days.append(NoClassDay(date=d, reason=reason[:100]))
    db.add(s)
    db.commit()
    return semester_out(s) | {"holidays_loaded": hol is not None}


@router.get("/semesters/{id}")
def get_semester(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return semester_out(get_owned(db, Semester, id, user), full=True)


@router.patch("/semesters/{id}")
def patch_semester(id: int, body: SemesterPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    data = body.model_dump(exclude_unset=True)
    if data.get("active"):
        db.execute(update(Semester).where(Semester.user_id == user.id).values(active=False))
    for k, v in data.items():
        setattr(s, k, v)
    if s.start_date >= s.end_date:
        raise HTTPException(422, "La fecha de inicio debe ser anterior a la de término")
    db.commit()
    return semester_out(s)


@router.delete("/semesters/{id}", status_code=204)
def delete_semester(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Semester, id, user))
    db.commit()
    return Response(status_code=204)


class NoClassIn(BaseModel):
    date: date
    reason: str = Field("", max_length=100)


@router.post("/semesters/{id}/no-class-days")
def add_no_class(id: int, body: NoClassIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    d = NoClassDay(semester_id=s.id, **body.model_dump())
    db.add(d)
    try:
        db.commit()
    except IntegrityError:
        raise HTTPException(409, "Ese día ya está marcado sin clases")
    return {"id": d.id, "date": d.date, "reason": d.reason}


@router.delete("/no-class-days/{id}", status_code=204)
def delete_no_class(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, NoClassDay, id, user))
    db.commit()
    return Response(status_code=204)


# ---------- ramos ----------
class SlotIn(BaseModel):
    id: int | None = None  # si viene, se conserva el bloque (y sus faltas)
    weekday: int = Field(ge=0, le=5)
    start_time: time
    end_time: time

    @model_validator(mode="after")
    def _horas(self):
        if self.start_time >= self.end_time:
            raise ValueError("La hora de inicio debe ser anterior a la de término")
        return self


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["T", "L"]
    min_pct: int = Field(ge=1, le=100)
    slots: list[SlotIn]


class CoursePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    kind: Literal["T", "L"] | None = None
    min_pct: int | None = Field(None, ge=1, le=100)
    slots: list[SlotIn] | None = None


@router.post("/semesters/{id}/courses")
def create_course(id: int, body: CourseIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    c = Course(semester_id=s.id, name=body.name, kind=body.kind, min_pct=body.min_pct,
               slots=[Slot(**x.model_dump(exclude={"id"})) for x in body.slots])
    db.add(c)
    db.commit()
    return course_out(c)


@router.post("/semesters/{id}/import-uls")
async def import_uls(id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    pdf = await request.body()
    found = await run_in_threadpool(parse_horario_uls, pdf) if len(pdf) <= 2_000_000 else []
    if not found:
        raise HTTPException(400, "No pude leer el horario. Sube el PDF de horario que entrega la ULS.")
    have = {(c.name, c.kind) for c in s.courses}
    new = [c for c in found if (c["name"], c["kind"]) not in have]
    for c in new:
        s.courses.append(Course(name=c["name"], kind=c["kind"], min_pct=70 if c["kind"] == "L" else 60, slots=[
            Slot(weekday=x["weekday"], start_time=time.fromisoformat(x["start_time"]), end_time=time.fromisoformat(x["end_time"]))
            for x in c["slots"]]))
    db.commit()
    return {"created": len(new), "skipped": len(found) - len(new)}


@router.patch("/courses/{id}")
def patch_course(id: int, body: CoursePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Course, id, user)
    data = body.model_dump(exclude_unset=True)
    if "slots" in data:
        old = {x.id: x for x in c.slots}
        new = []
        for x in data.pop("slots"):
            slot = old.get(x.pop("id", None)) or Slot()
            for k, v in x.items():
                setattr(slot, k, v)
            new.append(slot)
        c.slots = new
    for k, v in data.items():
        setattr(c, k, v)
    db.commit()
    return course_out(c)


class GradeItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    weight: float = Field(ge=0, le=100)  # % dentro de su parte (teoría o lab) si hay reparto; si no, de la nota final. 0 = aún no publicado
    grade: float | None = Field(None, ge=1, le=7)  # escala chilena; None = aún no se rinde
    date: dt.date | None = None
    kind: Literal["T", "L"] | None = None  # teoría o laboratorio


class GradesIn(BaseModel):
    meta: float = Field(4.0, ge=1, le=7)  # nota que quiere sacar (aprobar = 4,0)
    shares: dict[Literal["T", "L"], float] | None = None  # reparto de Phoenix, ej. {"T": 60, "L": 40}
    items: list[GradeItem] = Field(max_length=30)

    @model_validator(mode="after")
    def _suma(self):
        parts = {}  # con reparto, cada parte suma hasta 100% por separado
        for i in self.items:
            k = i.kind if self.shares and i.kind else None
            parts[k] = parts.get(k, 0) + i.weight
        if any(v > 100.001 for v in parts.values()) or sum((self.shares or {}).values()) > 100.001:
            raise ValueError("Los porcentajes suman más de 100%")
        return self


@router.put("/courses/{id}/grades")
def put_grades(id: int, body: GradesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Evaluaciones del ramo para calcular cuánto necesita; el cálculo se hace en la app."""
    c = get_owned(db, Course, id, user)
    c.grades = body.model_dump(mode="json", exclude_none=True) if body.items else None  # sin campos vacíos
    sync_agenda(db, c, user, body.items)
    db.commit()
    return course_out(c)


def sync_agenda(db: Session, c: Course, user: User, items: list[GradeItem]):
    """Las evaluaciones con fecha (las trae Phoenix) van solas a la agenda como pruebas, y se mueven o borran con ellas.
    Se actualizan en su lugar (mismo id) para no repetir el aviso de "Mañana". Si ya anotaste algo de ese ramo ese día, no se duplica."""
    mine = db.scalars(select(Event).where(Event.course_id == c.id)).all()
    taken = {e.date for e in mine if not e.auto}
    want = {i.name: i.date for i in items if i.date and i.date not in taken}
    for e in mine:
        if e.auto and e.title not in want:
            db.delete(e)
        elif e.auto:
            e.date = want.pop(e.title)
    db.add_all(Event(user_id=user.id, semester_id=c.semester_id, course_id=c.id, kind="prueba", date=d, title=t, auto=True)
               for t, d in want.items())


@router.delete("/courses/{id}", status_code=204)
def delete_course(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, Course, id, user)
    db.execute(delete(Event).where(Event.course_id == c.id, Event.auto))  # sus evaluaciones de Phoenix se van con el ramo
    db.delete(c)
    db.commit()
    return Response(status_code=204)


# ---------- faltas y resumen ----------
def today_param(today: date | None = Query(None)) -> date:
    return today or date.today()


def load_plan(db: Session, s: Semester) -> calc.Plan:
    slots = [x for c in s.courses for x in c.slots]
    ids = [x.id for x in slots]
    absences = db.execute(select(Absence.slot_id, Absence.date).where(Absence.slot_id.in_(ids))).all() if ids else []
    return calc.Plan(s.start_date, s.end_date, {d.date for d in s.no_class_days},
                     [calc.Course(c.id, c.name, c.kind, c.min_pct) for c in s.courses],
                     [calc.Slot(x.id, x.course_id, x.weekday) for x in slots],
                     {(a, d) for a, d in absences},
                     {(m.course_id, m.original, m.date) for c in s.courses for m in c.makeups})


def day_slots(db: Session, user: User, d: date, slot_ids: list[int] | None) -> list[Slot]:
    s = active_semester(db, user)
    p = load_plan(db, s) if s else None
    mine = {x.id: x for c in (s.courses if s else []) for x in c.slots if d in p.dates[x.id]}  # con feriados y recuperaciones
    if slot_ids is None:
        if not mine:
            raise HTTPException(400, "No tienes clases ese día")
        return list(mine.values())
    if any(i not in mine for i in slot_ids):
        raise HTTPException(400, "Ese bloque no tiene clases ese día")
    return [mine[i] for i in slot_ids]


def quedan_por_ramo(db: Session, user: User) -> dict[int, tuple[str, int]]:
    s = active_semester(db, user)
    return {c["id"]: (c["name"], c["quedan"]) for c in calc.summarize(load_plan(db, s), date.today())["courses"]} if s else {}


def alertar_faltas(db: Session, user: User, antes: dict[int, tuple[str, int]]) -> None:
    """Avisa solo al cruzar un umbral: queda 1 falta, quedan 0, o pasa a estar bajo el mínimo."""
    for cid, (name, q) in quedan_por_ramo(db, user).items():
        prev = antes.get(cid, (name, q))[1]
        if q >= prev or (q < 0 and prev < 0):
            continue
        title, body = (f"⚠️ Te queda 1 falta en {name}", "Puedes faltar solo una vez más sin quedar bajo el mínimo.") if q == 1 else \
            (f"🛑 No puedes faltar más a {name}", "Una falta más y quedas bajo el mínimo de asistencia.") if q == 0 else \
            (f"❌ Reprobarías {name} por asistencia", "Con estas faltas quedas bajo el mínimo.") if q < 0 else (None, None)
        if title:
            push.notify(db, [user.id], title, body, "/#inicio")


def mark_day(db: Session, user: User, d: date, slot_ids: list[int] | None) -> list[str]:
    antes = quedan_por_ramo(db, user)
    for x in day_slots(db, user, d, slot_ids):
        if not db.scalar(select(Absence.id).where(Absence.slot_id == x.id, Absence.date == d)):
            db.add(Absence(slot_id=x.id, date=d))
    db.commit()
    alertar_faltas(db, user, antes)
    return prueba_warnings(db, user, d)


class AbsenceIn(BaseModel):
    date: date
    slot_ids: list[int] | None = None


@router.post("/absences")
def add_absences(body: AbsenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"warnings": mark_day(db, user, body.date, body.slot_ids)}


@router.delete("/absences", status_code=204)
def remove_absences(body: AbsenceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = [x.id for x in day_slots(db, user, body.date, body.slot_ids)]
    db.execute(delete(Absence).where(Absence.slot_id.in_(ids), Absence.date == body.date))
    db.commit()
    return Response(status_code=204)


class RestIn(BaseModel):
    since: date
    absent: bool = True


@router.post("/slots/{id}/rest", status_code=204)
def mark_rest(id: int, body: RestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Tope de horario: desde `since`, todas las clases de este bloque quedan (o dejan de quedar) como falta."""
    x = db.get(Slot, id)
    if not x:
        raise HTTPException(404, "No encontrado")
    s = db.get(Semester, get_owned(db, Course, x.course_id, user).semester_id)
    antes = quedan_por_ramo(db, user)
    if body.absent:
        p = load_plan(db, s)
        db.add_all(Absence(slot_id=x.id, date=d) for d in sorted(p.dates[x.id]) if d >= body.since and (x.id, d) not in p.absences)
    else:
        db.execute(delete(Absence).where(Absence.slot_id == x.id, Absence.date >= body.since))
    db.commit()
    alertar_faltas(db, user, antes)
    return Response(status_code=204)


class ImportItem(BaseModel):
    course_id: int
    absent: list[date] = Field([], max_length=300)
    present: list[date] = Field([], max_length=300)


class ImportIn(BaseModel):
    items: list[ImportItem] = Field(max_length=50)


def phoenix_makeups(db: Session, c: Course, s: Semester, covered: set[date]) -> list[dict]:
    """Recuperaciones: cada fecha de Phoenix que no es del horario se empareja con la clase más cercana del
    horario que Phoenix no trae (esa clase se hizo ese otro día). Las que caen en fechas que Phoenix trae se rehacen;
    las demás (ej. anotadas a mano) se mantienen."""
    lo, hi = min(covered), max(covered)
    before = {(m.original, m.date) for m in c.makeups}
    keep = [m for m in c.makeups if m.date not in covered]
    weekdays = {x.weekday for x in c.slots}
    days = (lo + timedelta(i) for i in range((hi - lo).days + 1))
    sched = {d for d in days if d.weekday() in weekdays}  # incluye feriados: también se recuperan
    missing = sorted(sched - covered - {m.original for m in keep})
    pairs = []
    for d in sorted(covered - sched):
        if not missing:
            break
        # la más cercana (empate: la anterior). Si no era esa, el conteo da igual: ninguna de las dos está en Phoenix
        o = min(missing, key=lambda m: (abs((m - d).days), m))
        missing.remove(o)
        pairs.append((o, d))
    c.makeups = keep + [Makeup(original=o, date=d) for o, d in pairs]
    db.flush()
    return [{"course": c.name, "original": o.isoformat(), "date": d.isoformat()} for o, d in pairs if (o, d) not in before]


class MakeupIn(BaseModel):
    original: date
    date: date


@router.post("/courses/{id}/makeups")
def add_makeup(id: int, body: MakeupIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Recuperación anotada a mano: la clase del día `original` se hizo el día `date`."""
    c = get_owned(db, Course, id, user)
    s = db.get(Semester, c.semester_id)
    p = load_plan(db, s)
    if not any(body.original in p.dates[x.id] for x in c.slots):
        raise HTTPException(400, "Ese día el ramo no tenía clase")
    if not s.start_date <= body.date <= s.end_date or body.date == body.original:
        raise HTTPException(400, "La recuperación tiene que ser otro día del semestre")
    c.makeups.append(Makeup(original=body.original, date=body.date))
    db.commit()
    return course_out(c)


@router.delete("/makeups/{id}", status_code=204)
def delete_makeup(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Makeup, id)
    if not m:
        raise HTTPException(404, "No encontrado")
    get_owned(db, Course, m.course_id, user)
    db.delete(m)
    db.commit()
    return Response(status_code=204)


@router.post("/absences/import")
def import_absences(body: ImportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Registro oficial (Phoenix): en los días que trae, manda sobre lo marcado a mano."""
    added = removed = 0
    skipped, makeups = [], []
    antes = quedan_por_ramo(db, user)
    for it in body.items:
        c = get_owned(db, Course, it.course_id, user)
        s = db.get(Semester, c.semester_id)
        covered = {d for d in it.absent + it.present if s.start_date <= d <= s.end_date}
        if covered and c.slots:
            makeups += phoenix_makeups(db, c, s, covered)
        p = load_plan(db, s)
        for d, absent in [(d, True) for d in it.absent] + [(d, False) for d in it.present]:
            slots = [x for x in c.slots if d in p.dates[x.id]]
            if not slots and absent:
                skipped.append({"course": c.name, "date": d.isoformat()})  # ej: clase recuperativa en otro día
            for x in slots:
                have = db.scalar(select(Absence).where(Absence.slot_id == x.id, Absence.date == d))
                if absent and not have:
                    db.add(Absence(slot_id=x.id, date=d))
                    added += 1
                elif not absent and have:
                    db.delete(have)
                    removed += 1
    db.commit()
    alertar_faltas(db, user, antes)
    return {"added": added, "removed": removed, "skipped": skipped, "makeups": makeups}


@router.get("/semesters/{id}/summary")
def summary(id: int, today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    p = load_plan(db, s)
    full = semester_out(s, full=True)
    res = calc.summarize(p, today)
    extra = {c["id"]: {k: c[k] for k in ("slots", "makeups", "grades")} for c in full["courses"]}
    res["courses"] = [c | extra[c["id"]] for c in res["courses"]]
    return res | {
        "semester": semester_out(s),
        "no_class_days": full["no_class_days"],
        "absences": [{"slot_id": a, "date": d} for a, d in sorted(p.absences, key=lambda x: (x[1], x[0]))],
        "events": [event_out(e) for e in s.events],
    }


# ---------- amigos ----------
def friendship(db: Session, a: int, b: int) -> Friendship | None:
    return db.scalar(select(Friendship).where(or_(
        (Friendship.requester_id == a) & (Friendship.addressee_id == b),
        (Friendship.requester_id == b) & (Friendship.addressee_id == a))))


def are_friends(db: Session, a: int, b: int) -> bool:
    f = friendship(db, a, b)
    return bool(f and f.status == "accepted")


def color_on(db: Session, user: User, d: date, today: date) -> str:
    s = active_semester(db, user)
    return calc.day_color(load_plan(db, s), d, today) if s else "gris"


class FriendIn(BaseModel):
    username: str


@router.get("/friends")
def list_friends(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = {"friends": [], "incoming": [], "outgoing": []}
    rows = db.scalars(select(Friendship).where(or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id)))
    for f in rows:
        other = db.get(User, f.addressee_id if f.requester_id == user.id else f.requester_id)
        key = "friends" if f.status == "accepted" else "outgoing" if f.requester_id == user.id else "incoming"
        out[key].append(user_out(other))
    return out


@router.get("/friends/suggestions")
def friend_suggestions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # ponytail: carga todas las amistades aceptadas en memoria; pasar a un JOIN en SQL si hay miles de usuarios
    adj: dict[int, set[int]] = {}
    for a, b in db.execute(select(Friendship.requester_id, Friendship.addressee_id).where(Friendship.status == "accepted")):
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    mine = adj.get(user.id, set())
    related = {user.id} | set(db.scalars(select(Friendship.requester_id).where(Friendship.addressee_id == user.id))) \
        | set(db.scalars(select(Friendship.addressee_id).where(Friendship.requester_id == user.id)))
    mutual = {x: len(adj[x] & mine) for f in mine for x in adj[f] if x not in related}
    ids = sorted(mutual, key=lambda x: (-mutual[x], -x))[:10]
    ids += db.scalars(select(User.id).where(User.id.not_in(related | set(ids))).order_by(User.id.desc()).limit(10 - len(ids))).all()
    return [user_out(db.get(User, i)) | {"mutual": mutual.get(i, 0)} for i in ids]


@router.post("/friends")
def add_friend(body: FriendIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    other = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if not other:
        raise HTTPException(404, "Ese usuario no existe")
    if other.id == user.id:
        raise HTTPException(400, "No puedes agregarte a ti mismo")
    f = friendship(db, user.id, other.id)
    if f and f.status == "pending" and f.requester_id == other.id:
        f.status = "accepted"  # ya me había pedido: se acepta
    elif f:
        raise HTTPException(409, "Ya enviaste una solicitud o ya son amigos")
    else:
        f = Friendship(requester_id=user.id, addressee_id=other.id)
        db.add(f)
    db.commit()
    if f.status == "accepted":
        push.notify(db, [other.id], f"🤝 {user.display_name} aceptó tu solicitud", "Ahora pueden coordinar qué días faltar.", "/#amigos")
    else:
        push.notify(db, [other.id], f"👋 {user.display_name} quiere ser tu amigo", f"@{user.username} te envió una solicitud en Faltapp.", "/#amigos")
    return {"status": f.status}


@router.post("/friends/{id}/accept")
def accept_friend(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = friendship(db, user.id, id)
    if not f or f.status != "pending" or f.requester_id != id:
        raise HTTPException(404, "No encontrado")
    f.status = "accepted"
    db.commit()
    push.notify(db, [id], f"🤝 {user.display_name} aceptó tu solicitud", "Ahora pueden coordinar qué días faltar.", "/#amigos")
    return {"status": f.status}


@router.delete("/friends/{id}", status_code=204)
def delete_friend(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = friendship(db, user.id, id)
    if not f:
        raise HTTPException(404, "No encontrado")
    db.delete(f)
    db.commit()
    return Response(status_code=204)


@router.get("/friends/{id}/calendar")
def friend_calendar(id: int, today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not are_friends(db, user.id, id):
        raise HTTPException(404, "No encontrado")
    s = active_semester(db, db.get(User, id))
    return calc.summarize(load_plan(db, s), today)["calendar"] if s else {}


# ---------- propuestas ----------
def try_mark_day(db: Session, user: User, d: date) -> list[str]:
    try:
        return mark_day(db, user, d, None)
    except HTTPException:  # sin clases ese día: nada que marcar
        return []


class ProposalIn(BaseModel):
    date: date
    note: str = Field("", max_length=200)
    user_ids: list[int] = Field(min_length=1)


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
fecha = lambda d: f"{DIAS[d.weekday()]} {d.day}/{d.month:02d}"


class RespondIn(BaseModel):
    accept: bool


@router.post("/proposals")
def create_proposal(body: ProposalIn, today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    ids = set(body.user_ids) - {user.id}
    if not ids or not all(are_friends(db, user.id, i) for i in ids):
        raise HTTPException(404, "Solo puedes invitar a tus amigos")
    p = Proposal(creator_id=user.id, date=body.date, note=body.note,
                 members=[ProposalMember(user_id=user.id, status="accepted")] + [ProposalMember(user_id=i) for i in ids])
    db.add(p)
    db.commit()
    push.notify(db, sorted(ids), f"📅 {user.display_name} te propone faltar el {fecha(body.date)}", body.note or "¿Te sumas?", "/#propuestas")
    warnings = try_mark_day(db, user, body.date) or prueba_warnings(db, user, body.date)
    for i in sorted(ids):
        u = db.get(User, i)
        if color_on(db, u, body.date, today) == "rojo":
            warnings.append(f"{u.username} está en rojo ese día")
    return {"id": p.id, "warnings": warnings}


@router.get("/proposals")
def list_proposals(today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Proposal).join(ProposalMember).where(ProposalMember.user_id == user.id).order_by(Proposal.date.desc(), Proposal.id.desc())
    out = []
    for p in db.scalars(q):
        members = []
        for m in p.members:
            u = db.get(User, m.user_id)
            members.append(user_out(u) | {"status": m.status, "color": color_on(db, u, p.date, today)})
        out.append({"id": p.id, "date": p.date, "note": p.note, "creator": user_out(db.get(User, p.creator_id)), "members": members})
    return out


@router.post("/proposals/{id}/respond")
def respond_proposal(id: int, body: RespondIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(ProposalMember, (id, user.id))
    if not m:
        raise HTTPException(404, "No encontrado")
    m.status = "accepted" if body.accept else "rejected"
    db.commit()
    p = db.get(Proposal, id)
    if body.accept and p.creator_id != user.id:
        push.notify(db, [p.creator_id], f"✅ {user.display_name} se suma a faltar el {fecha(p.date)}", p.note or "Revisa quiénes van.", "/#propuestas")
    return {"warnings": try_mark_day(db, user, db.get(Proposal, id).date) if body.accept else []}


# ---------- agenda ----------
def prueba_warnings(db: Session, user: User, d: date) -> list[str]:
    q = select(Event.title).where(Event.user_id == user.id, Event.date == d, Event.kind == "prueba").order_by(Event.id)
    return [f"Tienes prueba ese día: {t}" for t in db.scalars(q)]


def event_out(e: Event) -> dict:
    return {"id": e.id, "course_id": e.course_id, "kind": e.kind, "date": e.date,
            "time": e.time.strftime("%H:%M") if e.time else None, "title": e.title, "auto": e.auto}


class EventIn(BaseModel):
    kind: Literal["prueba", "entrega", "reunion", "otro"]
    date: date
    time: dt.time | None = None
    title: str = Field(min_length=1, max_length=120)
    course_id: int | None = None


@router.get("/semesters/{id}/events")
def list_events(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [event_out(e) for e in get_owned(db, Semester, id, user).events]


@router.post("/semesters/{id}/events")
def create_event(id: int, body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    if body.course_id is not None and get_owned(db, Course, body.course_id, user).semester_id != s.id:
        raise HTTPException(404, "No encontrado")
    e = Event(user_id=user.id, semester_id=s.id, **body.model_dump())
    db.add(e)
    db.commit()
    return event_out(e)


@router.delete("/events/{id}", status_code=204)
def delete_event(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Event, id, user))
    db.commit()
    return Response(status_code=204)


# ---------- perfil público e insignias ----------
def friend_ids(db: Session, uid: int) -> set[int]:
    rows = db.execute(select(Friendship.requester_id, Friendship.addressee_id).where(
        Friendship.status == "accepted", or_(Friendship.requester_id == uid, Friendship.addressee_id == uid)))
    return {b if a == uid else a for a, b in rows}


def badges(db: Session, u: User, today: date) -> list[dict]:
    got = []
    if u.id <= 20:
        got.append(("fundador", "🚀", "Fundador", "De los primeros 20 en Faltapp"))
    if len(friend_ids(db, u.id)) >= 5:
        got.append(("sociable", "🤝", "Sociable", "5 amigos o más"))
    s = active_semester(db, u)
    if s and s.courses:
        stats = calc.summarize(load_plan(db, s), today)["courses"]
        if today > s.start_date and all(c["reales"] == 0 for c in stats):
            got.append(("perfecta", "⭐", "Asistencia perfecta", "Ninguna falta este semestre"))
        if all(c["quedan"] > 0 for c in stats):
            got.append(("verde", "🟢", "Todo en verde", "Todavía puede faltar en todos sus ramos"))
        if len(s.events) >= 3:
            got.append(("planificador", "📅", "Planificador", "3 o más pruebas o entregas anotadas"))
    if db.scalar(select(func.count()).select_from(ProposalMember).join(Proposal).where(
            Proposal.creator_id == u.id, ProposalMember.user_id != u.id, ProposalMember.status == "accepted")):
        got.append(("organizador", "🎉", "Organizador", "Alguien se sumó a una de sus propuestas"))
    return [{"id": i, "emoji": e, "label": label, "desc": d} for i, e, label, d in got]


@router.get("/users/{id}/profile")
def user_profile(id: int, today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(User, id)
    if not u:
        raise HTTPException(404, "No encontrado")
    mine, theirs = friend_ids(db, user.id), friend_ids(db, u.id)
    return profile_out(u) | {"friends": len(theirs), "mutual": len(mine & theirs) if u.id != user.id else 0,
                             "is_friend": u.id in mine, "badges": badges(db, u, today)}


# ---------- notificaciones ----------
class PushKeys(BaseModel):
    p256dh: str = Field(max_length=100)
    auth: str = Field(max_length=50)


class PushSub(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: PushKeys | None = None

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v: str) -> str:
        if not push.allowed_endpoint(v):
            raise ValueError("Ese servicio de notificaciones no está permitido")
        return v


@router.get("/push/key")
def push_key(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"key": push.public_key(db)}


@router.post("/push/subscribe", status_code=204)
def push_subscribe(body: PushSub, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not body.keys:
        raise HTTPException(422, "Faltan las claves de la suscripción")
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)) or PushSubscription(endpoint=body.endpoint)
    s.user_id, s.p256dh, s.auth = user.id, body.keys.p256dh, body.keys.auth  # el dispositivo queda con la cuenta actual
    db.add(s)
    db.commit()
    return Response(status_code=204)


@router.delete("/push/subscribe", status_code=204)
def push_unsubscribe(body: PushSub, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id))
    db.commit()
    return Response(status_code=204)


@router.post("/push/test", status_code=204)
def push_test(user: User = Depends(current_user), db: Session = Depends(get_db)):
    push.notify(db, [user.id], "🔔 Notificaciones activadas", "Así te avisaremos de pruebas, faltas y amigos.", "/#inicio")
    return Response(status_code=204)


@router.get("/cron/daily")
def cron_daily(key: str = "", today: date | None = None, db: Session = Depends(get_db)):
    """Lo llama cron-job.org cada tarde. Se puede llamar varias veces: no repite avisos."""
    secret = os.environ.get("CRON_SECRET")
    if not secret:
        raise HTTPException(503, "Falta configurar CRON_SECRET")
    if not hmac.compare_digest(key.encode(), secret.encode()):
        raise HTTPException(403, "Clave incorrecta")
    today = today or datetime.now(ZoneInfo("America/Santiago")).date()
    with_push = set(db.scalars(select(PushSubscription.user_id)))
    for s in db.scalars(select(Semester).where(Semester.active, Semester.user_id.in_(with_push))).all():
        uid, p = s.user_id, load_plan(db, s)
        res = calc.summarize(p, today)
        # ramos de hoy que aún no marca como falta (si ya marcó todo, o era falta planeada por un tope, no pregunta por esos)
        hoy = [c.name for c in s.courses if any(today in p.dates[x.id] and (x.id, today) not in p.absences for x in c.slots)]
        if hoy and res["calendar"].get(today.isoformat(), "gris") != "gris":
            push.notify(db, [uid], "¿Faltaste a alguna clase hoy?", f"Hoy tuviste {', '.join(hoy)}. Si faltaste, márcalo en un toque.",
                        "/#inicio", key=f"diario:{today}")
        for e in s.events:
            if e.date == today + timedelta(days=1):
                ramo = next((c.name for c in s.courses if c.id == e.course_id), "")
                detalle = " · ".join(x for x in (ramo, e.time and e.time.strftime("%H:%M")) if x) or "Revisa tu agenda."
                push.notify(db, [uid], f"📝 Mañana: {e.title}", detalle, "/#agenda", key=f"evento:{e.id}:{e.date}")
        nuevos = [c for c in res["courses"] if c["faltar_todo"] and push.claim(db, uid, f"todo:{c['id']}")]
        if nuevos:
            title = ("🎉 Ya puedes faltar a todo lo que queda del semestre" if all(c["faltar_todo"] for c in res["courses"])
                     else f"🎉 Ya puedes faltar a todo lo que queda en {', '.join(c['name'] for c in nuevos)}")
            push.notify(db, [uid], title, "Por asistencia ya cumples. Ojo con las pruebas.", "/#inicio")
    return {"ok": True}
