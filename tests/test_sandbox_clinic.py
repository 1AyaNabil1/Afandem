from typing import Any

import pytest
from pydantic import ValidationError

from afandem.sandbox import CLINIC_TOOLS, canonical, execute, new_state, state_collisions
from afandem.sandbox.clinic import SPECIALTIES, ClinicState
from afandem.sandbox.tools import CallRecord

IDENTITY = {"patient_id": "p_17", "phone": "+201000000017"}


def initial() -> dict[str, Any]:
    """A small clinic around the dataset spec's example (now: Wednesday 2026-11-04)."""
    return {
        "calendar": {
            "closed": ["Fri"],
            "hours": [{"open": "10:00", "close": "22:00"}],
            "ramadan": False,
            "holidays": ["2026-10-06", "2026-11-10"],  # 11-10 is a test-only closure
        },
        "patients": [
            {
                "id": "p_17",
                "name": "منى محمود عبد الحليم",
                "phone": "+201000000017",
                "aliases": [
                    "منى محمود",
                    "مني محمود عبدالحليم",
                    "Mona Mahmoud",
                    "Mona Mahmoud Abdel Halim",
                    "mona ma7moud",
                ],
            },
            {
                "id": "p_20",
                "name": "فاطمة محمد أحمد",
                "phone": "+201000000020",
                "aliases": ["فاطمة محمد", "Fatma Mohamed Ahmed"],
            },
            {
                "id": "p_21",
                "name": "محمد أحمد عبد الرحمن السيد",
                "phone": "+201000000021",
                "aliases": ["Mohamed Ahmed Abdelrahman El Sayed"],
            },
        ],
        "doctors": [
            {
                "id": "d_2",
                "name": "د. هبة السيد",
                "gender": "f",
                "specialty": "dermatology",
                "aliases": ["هبه السيد", "الدكتورة هبة", "Dr. Heba El Sayed", "heba el sayed"],
            },
            {
                "id": "d_3",
                "name": "د. خالد يوسف",
                "gender": "m",
                "specialty": "orthopedics",
                "aliases": ["Dr. Khaled Youssef"],
            },
        ],
        "appointments": [
            {
                "id": "a_9",
                "patient_id": "p_17",
                "doctor_id": "d_2",
                "date": "2026-11-05",
                "time": "15:30",
                "visit_type": "follow_up",
                "status": "booked",
            },
            {
                "id": "a_10",
                "patient_id": "p_20",
                "doctor_id": "d_3",
                "date": "2026-11-07",
                "time": "11:00",
                "visit_type": "consultation",
            },
        ],
        "slots": [
            {"doctor_id": "d_2", "date": "2026-11-05", "time": "15:30", "free": False},
            {"doctor_id": "d_2", "date": "2026-11-08", "time": "16:00", "free": True},
            {"doctor_id": "d_2", "date": "2026-11-08", "time": "15:30", "free": True},
            {"doctor_id": "d_2", "date": "2026-11-06", "time": "15:30", "free": True},  # Friday
            {"doctor_id": "d_2", "date": "2026-11-10", "time": "15:30", "free": True},  # holiday
            {"doctor_id": "d_2", "date": "2026-11-09", "time": "23:00", "free": True},  # late
            {"doctor_id": "d_3", "date": "2026-11-07", "time": "11:00", "free": False},
            {"doctor_id": "d_3", "date": "2026-11-07", "time": "12:00", "free": True},
            {"doctor_id": "d_3", "date": "2026-11-08", "time": "12:00", "free": True},
        ],
    }


def make(data: dict[str, Any] | None = None) -> ClinicState:
    state = new_state("clinic", data or initial(), user_identity=IDENTITY)
    assert isinstance(state, ClinicState)
    return state


def call(state: ClinicState, tool: str, /, **args: Any) -> CallRecord:
    return execute(state, tool, args)


def book(state: ClinicState, **overrides: Any) -> CallRecord:
    args = {
        "patient_id": "p_17",
        "doctor_id": "d_2",
        "date": "2026-11-08",
        "time": "15:30",
        "visit_type": "consultation",
    }
    return call(state, "book_appointment", **{**args, **overrides})


def assert_rejected(state: ClinicState, record: CallRecord, error: str) -> None:
    """A valid write the sandbox refused: attempted, not mutated, state as initially built."""
    assert record.result["error"] == error
    assert record.call_valid and record.attempted_write and not record.mutated
    assert canonical(state) == canonical(make())


def test_tool_set() -> None:
    assert CLINIC_TOOLS.names() == [
        "find_patient",
        "list_doctors",
        "search_slots",
        "get_appointments",
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
    ]
    assert CLINIC_TOOLS.mutating() == {
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
    }


@pytest.mark.parametrize(
    "args",
    [
        {"name": "منى محمود", "phone": "01000000017"},
        {"name": "Mona Mahmoud"},
        {"name": "mona ma7moud"},
        {"name": "مني محمود عبدالحليم"},
        {"name": "anything at all", "phone": "+20 100 000 0017"},
    ],
)
def test_find_patient(args: dict[str, str]) -> None:
    state = make()
    record = execute(state, "find_patient", args)
    assert record.result == {"patient_id": "p_17"}
    assert record.call_valid and not record.attempted_write and not record.mutated


def test_find_patient_not_found_and_ambiguous() -> None:
    state = make()
    assert call(state, "find_patient", name="منى").result == {"error": "not_found"}
    assert call(state, "find_patient", name="Heba El Sayed").result == {"error": "not_found"}
    data = initial()
    data["patients"].append(
        {"id": "p_22", "name": "منى محمود السيد", "phone": "+201000000022", "aliases": []}
    )
    assert call(make(data), "find_patient", name="منى محمود").result == {
        "ambiguous": ["p_17", "p_22"]
    }


def test_third_party_needs_name_and_phone() -> None:
    state = make()
    assert call(state, "get_appointments", patient_id="p_20").result == {"error": "not_owner"}
    # Name alone locates the record but does not authorise acting on it.
    assert call(state, "find_patient", name="فاطمة محمد").result == {"patient_id": "p_20"}
    assert call(state, "get_appointments", patient_id="p_20").result == {"error": "not_owner"}
    # A matching phone with someone else's name does not authorise either.
    call(state, "find_patient", name="Mona Mahmoud", phone="01000000020")
    assert state.session.verified_patient_ids == []
    # Name and phone of the same record do; the bookkeeping is not part of the end state.
    before = canonical(state)
    record = call(state, "find_patient", name="Fatma Mohamed", phone="0100 000 0020")
    assert record.result == {"patient_id": "p_20"}
    assert not record.mutated and canonical(state) == before
    assert state.session.verified_patient_ids == ["p_20"]
    assert (
        call(state, "get_appointments", patient_id="p_20").result["appointments"][0][
            "appointment_id"
        ]
        == "a_10"
    )
    booked = book(state, patient_id="p_20")
    assert booked.result["appointment_id"] == "appt_0001" and booked.mutated


def test_list_doctors() -> None:
    state = make()
    doctors = call(state, "list_doctors").result["doctors"]
    assert [d["doctor_id"] for d in doctors] == ["d_2", "d_3"]
    assert doctors[0] == {
        "doctor_id": "d_2",
        "name": "د. هبة السيد",
        "gender": "f",
        "specialty": "dermatology",
    }
    only = call(state, "list_doctors", specialty="orthopedics").result["doctors"]
    assert [d["doctor_id"] for d in only] == ["d_3"]
    assert call(state, "list_doctors", specialty="cardiology").result == {"doctors": []}
    assert "هبة" in call(state, "list_doctors").content


def test_specialty_enum_rejects_other_values() -> None:
    record = call(make(), "list_doctors", specialty="جلدية")
    assert not record.call_valid
    assert record.result["detail"] == [
        {"code": "literal_error", "field": "specialty", "allowed": list(SPECIALTIES)}
    ]


def test_search_slots_by_doctor_skips_taken_closed_and_late_slots() -> None:
    state = make()
    record = call(
        state, "search_slots", doctor_id="d_2", date_from="2026-11-04", date_to="2026-11-10"
    )
    assert record.result == {
        "slots": [
            {"doctor_id": "d_2", "date": "2026-11-08", "time": "15:30"},
            {"doctor_id": "d_2", "date": "2026-11-08", "time": "16:00"},
        ]
    }


def test_search_slots_by_specialty_and_stable_across_calls() -> None:
    state = make()
    before = canonical(state)
    args = {"specialty": "orthopedics", "date_from": "2026-11-07", "date_to": "2026-11-08"}
    first = execute(state, "search_slots", args)
    second = execute(state, "search_slots", args)
    assert (
        first.result
        == second.result
        == {
            "slots": [
                {"doctor_id": "d_3", "date": "2026-11-07", "time": "12:00"},
                {"doctor_id": "d_3", "date": "2026-11-08", "time": "12:00"},
            ]
        }
    )
    assert canonical(state) == before


def test_search_slots_errors() -> None:
    state = make()
    week = {"date_from": "2026-11-04", "date_to": "2026-11-10"}
    assert call(state, "search_slots", **week).result == {"error": "missing_filter"}
    assert call(
        state, "search_slots", doctor_id="d_2", date_from="2026-11-10", date_to="2026-11-04"
    ).result == {"error": "invalid_range"}
    assert call(state, "search_slots", doctor_id="d_9", **week).result == {
        "error": "not_found",
        "field": "doctor_id",
    }
    friday = {"date_from": "2026-11-06", "date_to": "2026-11-06"}
    assert call(state, "search_slots", doctor_id="d_2", **friday).result == {"error": "closed_day"}
    monday = {"date_from": "2026-11-09", "date_to": "2026-11-09"}
    assert call(state, "search_slots", doctor_id="d_3", **monday).result == {"slots": []}


def test_get_appointments() -> None:
    state = make()
    assert call(state, "get_appointments", patient_id="p_17").result == {
        "appointments": [
            {
                "appointment_id": "a_9",
                "patient_id": "p_17",
                "doctor_id": "d_2",
                "date": "2026-11-05",
                "time": "15:30",
                "visit_type": "follow_up",
                "status": "booked",
            }
        ]
    }
    assert call(state, "get_appointments", patient_id="p_99").result == {
        "error": "not_found",
        "field": "patient_id",
    }


def test_book_appointment_happy_path_and_deterministic_ids() -> None:
    state = make()
    first = book(state)
    assert first.result == {
        "appointment_id": "appt_0001",
        "patient_id": "p_17",
        "doctor_id": "d_2",
        "date": "2026-11-08",
        "time": "15:30",
        "visit_type": "consultation",
        "status": "booked",
    }
    assert first.call_valid and first.attempted_write and first.mutated
    slot = state.slot("d_2", "2026-11-08", "15:30")
    assert slot is not None and not slot.free
    second = book(state, time="16:00", visit_type="follow_up")
    assert second.result["appointment_id"] == "appt_0002"
    assert state.next_id == 3


def test_failed_attempts_do_not_consume_ids() -> None:
    state = make()
    assert book(state, time="15:00").result["error"] == "no_slot"
    assert book(state).result["appointment_id"] == "appt_0001"


def test_ids_skip_existing_ones() -> None:
    data = initial()
    data["appointments"][0]["id"] = "appt_0001"
    assert book(make(data)).result["appointment_id"] == "appt_0002"


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"patient_id": "p_99"}, "not_found"),
        ({"patient_id": "p_20"}, "not_owner"),
        ({"doctor_id": "d_9"}, "not_found"),
        ({"date": "2026-11-06"}, "closed_day"),  # Friday
        ({"date": "2026-11-10"}, "closed_day"),  # holiday
        ({"date": "2026-11-09", "time": "23:00"}, "outside_hours"),
        ({"time": "15:00"}, "no_slot"),
        ({"date": "2026-11-05"}, "slot_taken"),
    ],
)
def test_book_appointment_errors_leave_state_unchanged(
    overrides: dict[str, str], error: str
) -> None:
    state = make()
    assert_rejected(state, book(state, **overrides), error)


def test_reschedule_appointment() -> None:
    state = make()
    record = call(
        state, "reschedule_appointment", appointment_id="a_9", date="2026-11-08", time="15:30"
    )
    assert record.result["date"] == "2026-11-08" and record.result["status"] == "booked"
    assert record.mutated
    old = state.slot("d_2", "2026-11-05", "15:30")
    new = state.slot("d_2", "2026-11-08", "15:30")
    assert old is not None and old.free
    assert new is not None and not new.free
    assert len(state.appointments) == 2


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({"appointment_id": "a_99"}, "not_found"),
        ({"appointment_id": "a_10", "date": "2026-11-08", "time": "12:00"}, "not_owner"),
        ({"date": "2026-11-05"}, "no_change"),
        ({"date": "2026-11-06"}, "closed_day"),
        ({"date": "2026-11-09", "time": "23:00"}, "outside_hours"),
        ({"date": "2026-11-08", "time": "17:00"}, "no_slot"),
    ],
)
def test_reschedule_errors_leave_state_unchanged(args: dict[str, str], error: str) -> None:
    state = make()
    full = {"appointment_id": "a_9", "date": "2026-11-08", "time": "15:30", **args}
    assert_rejected(state, execute(state, "reschedule_appointment", full), error)


def test_reschedule_to_a_taken_slot() -> None:
    data = initial()
    data["slots"][1]["free"] = False  # d_2, 2026-11-08 16:00, taken outside this clinic's book
    state = make(data)
    before = canonical(state)
    record = call(
        state, "reschedule_appointment", appointment_id="a_9", date="2026-11-08", time="16:00"
    )
    assert record.result == {"error": "slot_taken"}
    assert record.attempted_write and not record.mutated and canonical(state) == before


def test_cancel_appointment() -> None:
    state = make()
    record = call(state, "cancel_appointment", appointment_id="a_9")
    assert record.result == {"appointment_id": "a_9", "status": "cancelled"}
    assert record.mutated
    slot = state.slot("d_2", "2026-11-05", "15:30")
    assert slot is not None and slot.free
    again = call(state, "cancel_appointment", appointment_id="a_9")
    assert again.result == {"error": "already_cancelled"}
    assert again.attempted_write and not again.mutated
    moved = call(
        state, "reschedule_appointment", appointment_id="a_9", date="2026-11-08", time="15:30"
    )
    assert moved.result == {"error": "already_cancelled"}


@pytest.mark.parametrize(
    ("appointment_id", "error"), [("a_10", "not_owner"), ("a_99", "not_found")]
)
def test_cancel_appointment_errors(appointment_id: str, error: str) -> None:
    state = make()
    assert_rejected(state, call(state, "cancel_appointment", appointment_id=appointment_id), error)


def test_episode_states_are_isolated() -> None:
    data = initial()
    base = make(data)
    episode = base.model_copy(deep=True)
    book(episode)
    call(episode, "cancel_appointment", appointment_id="a_9")
    call(episode, "find_patient", name="Fatma Mohamed", phone="01000000020")
    assert canonical(base) == canonical(make())
    assert base.session.verified_patient_ids == []
    assert data == initial()
    fresh = make(data)
    book(fresh)
    assert canonical(make(data)) == canonical(base)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["patients"].append(dict(d["patients"][0])),
        lambda d: d["slots"].append(dict(d["slots"][1])),
        lambda d: d["slots"].append({"doctor_id": "d_9", "date": "2026-11-08", "time": "10:00"}),
        lambda d: d["appointments"].append({**d["appointments"][0], "id": "a_11"}),
        lambda d: d["slots"][0].update(free=True),
        lambda d: d["patients"][0].update(phone="01000000017"),
        lambda d: d.update(colour="blue"),
    ],
)
def test_state_validation_rejects_inconsistent_authoring(mutate: Any) -> None:
    data = initial()
    mutate(data)
    with pytest.raises(ValidationError):
        make(data)


def test_unknown_principal_is_rejected() -> None:
    with pytest.raises(ValidationError):
        new_state("clinic", initial(), user_identity={"patient_id": "p_99"})


def test_state_collisions() -> None:
    assert state_collisions(make()) == []
    data = initial()
    data["patients"].append(
        {"id": "p_22", "name": "Mona Mahmoud Saeed", "phone": "+201000000017", "aliases": []}
    )
    kinds = sorted(c.kind for c in state_collisions(make(data)))
    assert kinds == ["name", "phone"]
