import datetime as dt
from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now():
    return datetime.now(timezone.utc)


def _fk(target):
    return mapped_column(ForeignKey(target, ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # perfil
    bio: Mapped[str] = mapped_column(String(160), default="", server_default="")
    career: Mapped[str] = mapped_column(String(60), default="", server_default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(60), default="", server_default="")
    banner_color: Mapped[str] = mapped_column(String(7), default="#4f46e5", server_default="#4f46e5")
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)  # solo se carga al pedir la foto
    avatar_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    avatar_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    username_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    display_name_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("requester_id", "addressee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = _fk("users.id")
    addressee_id: Mapped[int] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Semester(Base):
    __tablename__ = "semesters"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("users.id")
    name: Mapped[str] = mapped_column(String(60))
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)
    country_code: Mapped[str] = mapped_column(String(2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    no_class_days: Mapped[list["NoClassDay"]] = relationship(cascade="all, delete-orphan", order_by="NoClassDay.date")
    courses: Mapped[list["Course"]] = relationship(cascade="all, delete-orphan", order_by="Course.id")
    events: Mapped[list["Event"]] = relationship(cascade="all, delete-orphan", order_by="Event.date")


class NoClassDay(Base):
    __tablename__ = "no_class_days"
    __table_args__ = (UniqueConstraint("semester_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = _fk("semesters.id")
    date: Mapped[dt.date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(100), default="")


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    semester_id: Mapped[int] = _fk("semesters.id")
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(1))
    min_pct: Mapped[int] = mapped_column(Integer)
    slots: Mapped[list["Slot"]] = relationship(cascade="all, delete-orphan", order_by="Slot.weekday")


class Slot(Base):
    __tablename__ = "slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = _fk("courses.id")
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[dt.time] = mapped_column(Time)
    end_time: Mapped[dt.time] = mapped_column(Time)
    absences: Mapped[list["Absence"]] = relationship(cascade="all, delete-orphan")


class Absence(Base):
    __tablename__ = "absences"
    __table_args__ = (UniqueConstraint("slot_id", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    slot_id: Mapped[int] = _fk("slots.id")
    date: Mapped[dt.date] = mapped_column(Date)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    creator_id: Mapped[int] = _fk("users.id")
    date: Mapped[dt.date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    members: Mapped[list["ProposalMember"]] = relationship(cascade="all, delete-orphan")


class ProposalMember(Base):
    __tablename__ = "proposal_members"
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("users.id")
    semester_id: Mapped[int] = _fk("semesters.id")
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(10))
    date: Mapped[dt.date] = mapped_column(Date)
    time: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    title: Mapped[str] = mapped_column(String(120))


# ---------- notificaciones push ----------
class PushSubscription(Base):
    """Un navegador/dispositivo que aceptó notificaciones."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = _fk("users.id")
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(String(100))
    auth: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SentPush(Base):
    """Avisos ya enviados (ej. "diario:2026-10-02"), para no repetirlos si el cron corre dos veces."""
    __tablename__ = "sent_pushes"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)


class AppSetting(Base):
    """Valores del servidor que se generan solos (ej. las claves VAPID de las notificaciones)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
