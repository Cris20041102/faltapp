import datetime as dt
from datetime import datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint
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
