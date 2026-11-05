"""Clinic sandbox: state and the seven tools.

Policy enforced here (the system prompt's policy block states it): the authenticated patient may
read and change their own appointments; another patient's only after that patient has been
located in this episode with both name and phone, i.e. a `find_patient` call whose phone and
name both match the record (the third-party rule). Anything else on another patient's records
returns `{"error": "not_owner"}`. `search_slots` and `book_appointment` (and the new date of
`reschedule_appointment`) are gated by the clinic calendar.
"""

from datetime import timedelta
from typing import Any, Literal, Self, get_args

from pydantic import Field, model_validator

from afandem.sandbox.calendar import ClinicCalendar, closure, is_open_day
from afandem.sandbox.clock import parse_date, same_date
from afandem.sandbox.fields import E164, Args, Hhmm, Id, IsoDate, PersonName, PhoneArg, StateModel
from afandem.sandbox.names import Collision, alias_collisions, lookup, name_matches, phone_matches
from afandem.sandbox.names import phone_collisions as _phone_collisions
from afandem.sandbox.tools import JSONDict, ToolRegistry

Specialty = Literal[
    "orthopedics",
    "internal_medicine",
    "pediatrics",
    "gynecology",
    "dermatology",
    "dentistry",
    "ophthalmology",
    "cardiology",
    "neurology",
    "ent",
    "psychiatry",
    "urology",
    "pulmonology",
    "endocrinology",
    "physiotherapy",
    "nutrition",
]
SPECIALTIES: tuple[str, ...] = get_args(Specialty)
VisitType = Literal["consultation", "follow_up"]


class Patient(StateModel):
    id: Id
    name: PersonName
    phone: E164 | None = None
    aliases: list[str] = Field(default_factory=list)
    gender: Literal["f", "m"] | None = None
    age: int | None = Field(default=None, ge=0, le=120)


class Doctor(StateModel):
    id: Id
    name: PersonName
    gender: Literal["f", "m"]
    specialty: Specialty
    aliases: list[str] = Field(default_factory=list)


class Slot(StateModel):
    doctor_id: Id
    date: IsoDate
    time: Hhmm
    free: bool = True


class Appointment(StateModel):
    id: Id
    patient_id: Id
    doctor_id: Id
    date: IsoDate
    time: Hhmm
    visit_type: VisitType
    status: Literal["booked", "cancelled"] = "booked"


class ClinicIdentity(StateModel):
    patient_id: Id
    phone: E164 | None = None


class ClinicSession(StateModel):
    """Episode bookkeeping, left out of `canonical()`: who was located with name and phone."""

    verified_patient_ids: list[str] = Field(default_factory=list)


def _duplicates(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    repeated: list[Any] = []
    for value in values:
        if value in seen:
            repeated.append(value)
        seen.add(value)
    return repeated


class ClinicState(StateModel):
    user_identity: ClinicIdentity
    calendar: ClinicCalendar
    patients: list[Patient]
    doctors: list[Doctor]
    slots: list[Slot] = Field(default_factory=list)
    appointments: list[Appointment] = Field(default_factory=list)
    next_id: int = Field(default=1, ge=1)
    session: ClinicSession = Field(default_factory=ClinicSession)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        problems: list[str] = []
        for label, ids in (
            ("patient", [p.id for p in self.patients]),
            ("doctor", [d.id for d in self.doctors]),
            ("appointment", [a.id for a in self.appointments]),
            ("slot", [(s.doctor_id, s.date, s.time) for s in self.slots]),
        ):
            problems += [f"duplicate {label} {dup}" for dup in _duplicates(ids)]
        patients = {p.id for p in self.patients}
        doctors = {d.id for d in self.doctors}
        if self.user_identity.patient_id not in patients:
            problems.append(f"user_identity.patient_id {self.user_identity.patient_id} unknown")
        problems += [
            f"slot for unknown doctor {s.doctor_id}"
            for s in self.slots
            if s.doctor_id not in doctors
        ]
        booked: list[tuple[str, str, str]] = []
        for a in self.appointments:
            if a.patient_id not in patients or a.doctor_id not in doctors:
                problems.append(f"appointment {a.id} references an unknown patient or doctor")
            if a.status == "booked":
                booked.append((a.doctor_id, a.date, a.time))
                slot = self.slot(a.doctor_id, a.date, a.time)
                if slot is not None and slot.free:
                    problems.append(f"appointment {a.id} is booked but its slot is free")
        problems += [f"two booked appointments in slot {dup}" for dup in _duplicates(booked)]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def patient(self, patient_id: str) -> Patient | None:
        return next((p for p in self.patients if p.id == patient_id), None)

    def doctor(self, doctor_id: str) -> Doctor | None:
        return next((d for d in self.doctors if d.id == doctor_id), None)

    def appointment(self, appointment_id: str) -> Appointment | None:
        return next((a for a in self.appointments if a.id == appointment_id), None)

    def slot(self, doctor_id: str, date: str, time: str) -> Slot | None:
        return next(
            (
                s
                for s in self.slots
                if s.doctor_id == doctor_id and same_date(s.date, date) and s.time == time
            ),
            None,
        )

    def may_act_for(self, patient_id: str) -> bool:
        """The principal, or a patient located with name and phone in this episode."""
        return (
            patient_id == self.user_identity.patient_id
            or patient_id in self.session.verified_patient_ids
        )

    def identity_collisions(self) -> list[Collision]:
        """State-collision lint: patients or doctors the lookup cannot tell apart."""
        return (
            alias_collisions(self.patients)
            + _phone_collisions(self.patients)
            + alias_collisions(self.doctors)
        )


CLINIC_TOOLS: ToolRegistry[ClinicState] = ToolRegistry("clinic", ClinicState)


def _error(code: str, **extra: Any) -> JSONDict:
    return {"error": code, **extra}


def _appointment_view(a: Appointment) -> JSONDict:
    return {
        "appointment_id": a.id,
        "patient_id": a.patient_id,
        "doctor_id": a.doctor_id,
        "date": a.date,
        "time": a.time,
        "visit_type": a.visit_type,
        "status": a.status,
    }


def _bookable_slot(state: ClinicState, doctor_id: str, date: str, time: str) -> Slot | JSONDict:
    """The free slot at that date and time, or the calendar or slot error."""
    if (closed := closure(state.calendar, date, time)) is not None:
        return _error(closed)
    slot = state.slot(doctor_id, date, time)
    if slot is None:
        return _error("no_slot")
    if not slot.free:
        return _error("slot_taken")
    return slot


def _new_appointment_id(state: ClinicState) -> str:
    existing = {a.id for a in state.appointments}
    while True:
        candidate = f"appt_{state.next_id:04d}"
        state.next_id += 1
        if candidate not in existing:
            return candidate


class FindPatientArgs(Args):
    name: PersonName
    phone: PhoneArg | None = None


@CLINIC_TOOLS.tool(mutates=False)
def find_patient(state: ClinicState, args: FindPatientArgs) -> JSONDict:
    """Find a patient's id by name (at least two name parts) and, optionally, phone.

    The phone is matched first. Returns {"patient_id"}, {"ambiguous": [patient_id, ...]} or
    {"error": "not_found"}.
    """
    found = lookup(state.patients, name=args.name, phone=args.phone)
    if not isinstance(found, str):
        return dict(found)
    patient = state.patient(found)
    if (
        patient is not None
        and args.phone is not None
        and phone_matches(patient, args.phone)
        and name_matches(patient, args.name)
        and found not in state.session.verified_patient_ids
    ):
        state.session.verified_patient_ids.append(found)
    return {"patient_id": found}


class ListDoctorsArgs(Args):
    specialty: Specialty | None = None


@CLINIC_TOOLS.tool(mutates=False)
def list_doctors(state: ClinicState, args: ListDoctorsArgs) -> JSONDict:
    """List the clinic's doctors, optionally only one specialty. Returns {"doctors": [...]}."""
    return {
        "doctors": [
            {"doctor_id": d.id, "name": d.name, "gender": d.gender, "specialty": d.specialty}
            for d in state.doctors
            if args.specialty is None or d.specialty == args.specialty
        ]
    }


class SearchSlotsArgs(Args):
    doctor_id: Id | None = None
    specialty: Specialty | None = None
    date_from: IsoDate
    date_to: IsoDate


@CLINIC_TOOLS.tool(mutates=False)
def search_slots(state: ClinicState, args: SearchSlotsArgs) -> JSONDict:
    """Free slots from date_from to date_to (inclusive) for a doctor_id or a specialty.

    Returns {"slots": [{"doctor_id", "date", "time"}, ...]}. Errors: missing_filter,
    invalid_range, not_found, closed_day (every date in the range is a closed day).
    """
    if args.doctor_id is None and args.specialty is None:
        return _error("missing_filter")
    start, end = parse_date(args.date_from), parse_date(args.date_to)
    if start > end:
        return _error("invalid_range")
    if args.doctor_id is not None and state.doctor(args.doctor_id) is None:
        return _error("not_found", field="doctor_id")
    doctors = {
        d.id
        for d in state.doctors
        if (args.doctor_id is None or d.id == args.doctor_id)
        and (args.specialty is None or d.specialty == args.specialty)
    }
    found = sorted(
        (
            s
            for s in state.slots
            if s.doctor_id in doctors
            and s.free
            and start <= parse_date(s.date) <= end
            and closure(state.calendar, s.date, s.time) is None
        ),
        key=lambda s: (s.date, s.time, s.doctor_id),
    )
    if not found and not any(
        is_open_day(state.calendar, start + timedelta(days=offset))
        for offset in range((end - start).days + 1)
    ):
        return _error("closed_day")
    return {"slots": [{"doctor_id": s.doctor_id, "date": s.date, "time": s.time} for s in found]}


class GetAppointmentsArgs(Args):
    patient_id: Id


@CLINIC_TOOLS.tool(mutates=False)
def get_appointments(state: ClinicState, args: GetAppointmentsArgs) -> JSONDict:
    """A patient's appointments. Returns {"appointments": [...]}. Errors: not_found, not_owner."""
    if state.patient(args.patient_id) is None:
        return _error("not_found", field="patient_id")
    if not state.may_act_for(args.patient_id):
        return _error("not_owner")
    mine = sorted(
        (a for a in state.appointments if a.patient_id == args.patient_id),
        key=lambda a: (a.date, a.time, a.id),
    )
    return {"appointments": [_appointment_view(a) for a in mine]}


class BookAppointmentArgs(Args):
    patient_id: Id
    doctor_id: Id
    date: IsoDate
    time: Hhmm
    visit_type: VisitType = Field(
        description="consultation: a new visit; follow_up: a return visit"
    )


@CLINIC_TOOLS.tool(mutates=True)
def book_appointment(state: ClinicState, args: BookAppointmentArgs) -> JSONDict:
    """Book a free slot for a patient. Returns the appointment.

    Errors: not_found, not_owner, closed_day, outside_hours, no_slot, slot_taken.
    """
    if state.patient(args.patient_id) is None:
        return _error("not_found", field="patient_id")
    if not state.may_act_for(args.patient_id):
        return _error("not_owner")
    if state.doctor(args.doctor_id) is None:
        return _error("not_found", field="doctor_id")
    slot = _bookable_slot(state, args.doctor_id, args.date, args.time)
    if not isinstance(slot, Slot):
        return slot
    appointment = Appointment(
        id=_new_appointment_id(state),
        patient_id=args.patient_id,
        doctor_id=args.doctor_id,
        date=args.date,
        time=args.time,
        visit_type=args.visit_type,
    )
    slot.free = False
    state.appointments.append(appointment)
    return _appointment_view(appointment)


class RescheduleAppointmentArgs(Args):
    appointment_id: Id
    date: IsoDate
    time: Hhmm


@CLINIC_TOOLS.tool(mutates=True)
def reschedule_appointment(state: ClinicState, args: RescheduleAppointmentArgs) -> JSONDict:
    """Move a booked appointment to another free slot of the same doctor.

    Errors: not_found, not_owner, already_cancelled, no_change, closed_day, outside_hours,
    no_slot, slot_taken.
    """
    appointment = state.appointment(args.appointment_id)
    if appointment is None:
        return _error("not_found", field="appointment_id")
    if not state.may_act_for(appointment.patient_id):
        return _error("not_owner")
    if appointment.status != "booked":
        return _error("already_cancelled")
    if same_date(appointment.date, args.date) and appointment.time == args.time:
        return _error("no_change")
    target = _bookable_slot(state, appointment.doctor_id, args.date, args.time)
    if not isinstance(target, Slot):
        return target
    old = state.slot(appointment.doctor_id, appointment.date, appointment.time)
    if old is not None:
        old.free = True
    target.free = False
    appointment.date, appointment.time = args.date, args.time
    return _appointment_view(appointment)


class CancelAppointmentArgs(Args):
    appointment_id: Id


@CLINIC_TOOLS.tool(mutates=True)
def cancel_appointment(state: ClinicState, args: CancelAppointmentArgs) -> JSONDict:
    """Cancel a booked appointment and free its slot.

    Errors: not_found, not_owner, already_cancelled.
    """
    appointment = state.appointment(args.appointment_id)
    if appointment is None:
        return _error("not_found", field="appointment_id")
    if not state.may_act_for(appointment.patient_id):
        return _error("not_owner")
    if appointment.status != "booked":
        return _error("already_cancelled")
    slot = state.slot(appointment.doctor_id, appointment.date, appointment.time)
    if slot is not None:
        slot.free = True
    appointment.status = "cancelled"
    return {"appointment_id": appointment.id, "status": appointment.status}
