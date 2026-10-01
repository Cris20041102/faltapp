import datetime as dt
import os
import re
from datetime import date, time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import current_user, hash_password, make_token, verify_password
from app.horario_uls import parse as parse_horario_uls
from app import calc
from app.db import get_db
from app.models import Absence, Course, Event, Friendship, NoClassDay, Proposal, ProposalMember, Semester, Slot, User

router = APIRouter(prefix="/api")


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name}


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
        if not re.fullmatch(r"[a-z0-9_.]{3,30}", v):
            raise ValueError("El usuario debe tener de 3 a 30 caracteres: letras, números, punto o guion bajo")
        return v

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
    return user_out(user)


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
    return {"id": c.id, "name": c.name, "kind": c.kind, "min_pct": c.min_pct, "slots": [slot_out(s) for s in c.slots]}


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


@router.delete("/courses/{id}", status_code=204)
def delete_course(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(get_owned(db, Course, id, user))
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
                     {(a, d) for a, d in absences})


def day_slots(db: Session, user: User, d: date, slot_ids: list[int] | None) -> list[Slot]:
    s = active_semester(db, user)
    off = {x.date for x in s.no_class_days} if s else set()
    valid = s and s.start_date <= d <= s.end_date and d not in off
    mine = {x.id: x for c in (s.courses if s else []) for x in c.slots}
    if slot_ids is None:
        chosen = [x for x in mine.values() if valid and x.weekday == d.weekday()]
        if not chosen:
            raise HTTPException(400, "No tienes clases ese día")
        return chosen
    if not valid or any(i not in mine or mine[i].weekday != d.weekday() for i in slot_ids):
        raise HTTPException(400, "Ese bloque no tiene clases ese día")
    return [mine[i] for i in slot_ids]


def mark_day(db: Session, user: User, d: date, slot_ids: list[int] | None) -> list[str]:
    for x in day_slots(db, user, d, slot_ids):
        if not db.scalar(select(Absence.id).where(Absence.slot_id == x.id, Absence.date == d)):
            db.add(Absence(slot_id=x.id, date=d))
    db.commit()
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


@router.get("/semesters/{id}/summary")
def summary(id: int, today: date = Depends(today_param), user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_owned(db, Semester, id, user)
    p = load_plan(db, s)
    full = semester_out(s, full=True)
    res = calc.summarize(p, today)
    slots = {c["id"]: c["slots"] for c in full["courses"]}
    res["courses"] = [c | {"slots": slots[c["id"]]} for c in res["courses"]]
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
    return {"status": f.status}


@router.post("/friends/{id}/accept")
def accept_friend(id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = friendship(db, user.id, id)
    if not f or f.status != "pending" or f.requester_id != id:
        raise HTTPException(404, "No encontrado")
    f.status = "accepted"
    db.commit()
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
    return {"warnings": try_mark_day(db, user, db.get(Proposal, id).date) if body.accept else []}


# ---------- agenda ----------
def prueba_warnings(db: Session, user: User, d: date) -> list[str]:
    q = select(Event.title).where(Event.user_id == user.id, Event.date == d, Event.kind == "prueba").order_by(Event.id)
    return [f"Tienes prueba ese día: {t}" for t in db.scalars(q)]


def event_out(e: Event) -> dict:
    return {"id": e.id, "course_id": e.course_id, "kind": e.kind, "date": e.date,
            "time": e.time.strftime("%H:%M") if e.time else None, "title": e.title}


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
