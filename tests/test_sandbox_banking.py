from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from afandem.sandbox import BANKING_TOOLS, canonical, execute, new_state, state_collisions
from afandem.sandbox.banking import BankingState, egp_to_piastres, piastres_to_egp
from afandem.sandbox.tools import CallRecord

IDENTITY = {"customer_id": "c_1", "phone": "+201000000030"}
NOW = {"local": "2026-11-04T10:00:00", "tz": "Africa/Cairo", "weekday": "Wednesday"}


def initial() -> dict[str, Any]:
    return {
        "daily_limit_piastres": egp_to_piastres(50_000),
        "accounts": [
            {"id": "acc_1", "owner_id": "c_1", "balance_piastres": egp_to_piastres(125_000)},
            {"id": "acc_2", "owner_id": "c_1", "kind": "savings", "balance_piastres": 125_000},
            {"id": "acc_9", "owner_id": "c_2", "balance_piastres": egp_to_piastres(10_000)},
            {"id": "acc_7", "owner_id": "c_3", "balance_piastres": egp_to_piastres(3_000)},
        ],
        "cards": [
            {"last4": "4821", "account_id": "acc_1"},
            {"last4": "1234", "account_id": "acc_7"},
        ],
        "beneficiaries": [
            {
                "owner_id": "c_1",
                "account_id": "acc_9",
                "name": "محمد أحمد عبد الرحمن السيد",
                "aliases": ["محمد أحمد", "Mohamed Ahmed Abdelrahman"],
                "phone": "+201000000031",
            },
            {
                "owner_id": "c_1",
                "account_id": "EG-EXT-0042",
                "name": "هبة السيد",
                "aliases": ["Heba El Sayed"],
            },
            {"owner_id": "c_3", "account_id": "acc_1", "name": "منى محمود عبد الحليم"},
        ],
        "transactions": [
            {
                "id": "t_1",
                "date": "2026-11-01",
                "kind": "card",
                "from_account_id": "acc_1",
                "amount_piastres": 35_050,
            },
            {
                "id": "t_2",
                "date": "2026-11-03",
                "kind": "deposit",
                "to_account_id": "acc_1",
                "amount_piastres": egp_to_piastres(10_000),
            },
            {
                "id": "t_3",
                "date": "2026-11-04",
                "kind": "transfer",
                "from_account_id": "acc_1",
                "to_account_id": "acc_9",
                "amount_piastres": egp_to_piastres(10_000),
            },
        ],
    }


def make(data: dict[str, Any] | None = None) -> BankingState:
    state = new_state("banking", data or initial(), user_identity=IDENTITY, now=NOW)
    assert isinstance(state, BankingState)
    return state


def call(state: BankingState, tool: str, /, **args: Any) -> CallRecord:
    return execute(state, tool, args)


def send(state: BankingState, **overrides: Any) -> CallRecord:
    args = {"from_account_id": "acc_1", "to_account_id": "acc_9", "amount_egp": 5_000}
    return call(state, "transfer", **{**args, **overrides})


def balance(state: BankingState, account_id: str) -> int:
    account = state.account(account_id)
    assert account is not None
    return account.balance_piastres


def assert_rejected(state: BankingState, record: CallRecord, error: str) -> None:
    assert record.result["error"] == error
    assert record.call_valid and record.attempted_write and not record.mutated
    assert canonical(state) == canonical(make())


def test_tool_set() -> None:
    assert BANKING_TOOLS.names() == [
        "get_balance",
        "list_transactions",
        "list_beneficiaries",
        "transfer",
        "block_card",
    ]
    assert BANKING_TOOLS.mutating() == {"transfer", "block_card"}


def test_money_conversions() -> None:
    assert piastres_to_egp(125_000) == 1250
    assert isinstance(piastres_to_egp(125_000), int)
    assert piastres_to_egp(35_050) == 350.5
    assert piastres_to_egp(5) == 0.05
    assert egp_to_piastres(1250) == 125_000


def test_get_balance() -> None:
    state = make()
    assert call(state, "get_balance", account_id="acc_2").result == {
        "account_id": "acc_2",
        "kind": "savings",
        "balance_egp": 1250,
    }
    assert call(state, "get_balance", account_id="acc_9").result == {"error": "not_owner"}
    assert call(state, "get_balance", account_id="acc_404").result == {
        "error": "not_found",
        "field": "account_id",
    }


def test_list_transactions() -> None:
    state = make()
    rows = call(
        state, "list_transactions", account_id="acc_1", date_from="2026-11-01", date_to="2026-11-03"
    ).result["transactions"]
    assert rows == [
        {
            "transaction_id": "t_1",
            "date": "2026-11-01",
            "kind": "card",
            "direction": "out",
            "amount_egp": 350.5,
        },
        {
            "transaction_id": "t_2",
            "date": "2026-11-03",
            "kind": "deposit",
            "direction": "in",
            "amount_egp": 10_000,
        },
    ]
    today = call(
        state, "list_transactions", account_id="acc_1", date_from="2026-11-04", date_to="2026-11-04"
    ).result["transactions"]
    assert today[0]["counterparty_account_id"] == "acc_9"
    assert call(
        state, "list_transactions", account_id="acc_1", date_from="2026-11-04", date_to="2026-11-01"
    ).result == {"error": "invalid_range"}
    assert call(
        state, "list_transactions", account_id="acc_7", date_from="2026-11-01", date_to="2026-11-04"
    ).result == {"error": "not_owner"}


def test_list_beneficiaries() -> None:
    state = make()
    everyone = call(state, "list_beneficiaries", account_id="acc_1").result
    assert everyone == {
        "beneficiaries": [
            {"account_id": "acc_9", "name": "محمد أحمد عبد الرحمن السيد"},
            {"account_id": "EG-EXT-0042", "name": "هبة السيد"},
        ]
    }
    for query in (
        {"name": "محمد أحمد"},
        {"name": "Muhammad Ahmad"},
        {"phone": "0100 000 0031"},
        {"name": "Heba El Sayed", "phone": "01000000031"},  # the phone wins
    ):
        found = execute(state, "list_beneficiaries", {"account_id": "acc_1", **query}).result
        assert [b["account_id"] for b in found["beneficiaries"]] == ["acc_9"]
    assert call(state, "list_beneficiaries", account_id="acc_1", name="منى محمود").result == {
        "error": "not_found"
    }
    assert call(state, "list_beneficiaries", account_id="acc_7").result == {"error": "not_owner"}


def test_list_beneficiaries_ambiguous() -> None:
    data = initial()
    data["beneficiaries"].append(
        {"owner_id": "c_1", "account_id": "acc_8", "name": "محمد أحمد علي", "aliases": []}
    )
    state = make(data)
    assert call(state, "list_beneficiaries", account_id="acc_1", name="محمد أحمد").result == {
        "ambiguous": ["acc_8", "acc_9"]
    }
    assert [c.kind for c in state_collisions(state)] == ["name"]


def test_transfer_to_beneficiary_in_this_bank() -> None:
    state = make()
    record = send(state, note="rent")
    assert record.result == {
        "transaction_id": "txn_0001",
        "from_account_id": "acc_1",
        "to_account_id": "acc_9",
        "amount_egp": 5_000,
        "balance_egp": 120_000,
    }
    assert record.call_valid and record.attempted_write and record.mutated
    assert balance(state, "acc_1") == egp_to_piastres(120_000)
    assert balance(state, "acc_9") == egp_to_piastres(15_000)
    added = state.transactions[-1]
    assert (added.date, added.counterparty, added.note) == (
        "2026-11-04",
        "محمد أحمد عبد الرحمن السيد",
        "rent",
    )
    assert send(state, amount_egp=1).result["transaction_id"] == "txn_0002"


def test_transfer_to_external_beneficiary_and_between_own_accounts() -> None:
    state = make()
    assert send(state, to_account_id="EG-EXT-0042", amount_egp=1_000).mutated
    assert balance(state, "acc_1") == egp_to_piastres(124_000)
    assert send(state, to_account_id="acc_2", amount_egp=1_000).mutated
    assert balance(state, "acc_2") == 125_000 + egp_to_piastres(1_000)


def test_transfer_daily_limit() -> None:
    state = make()  # 10,000 EGP already transferred today, limit 50,000
    over = send(state, amount_egp=40_001)
    assert over.result == {
        "error": "limit_exceeded",
        "daily_limit_egp": 50_000,
        "remaining_egp": 40_000,
    }
    assert over.call_valid and over.attempted_write and not over.mutated
    assert canonical(state) == canonical(make())
    assert send(state, amount_egp=40_000).mutated
    assert send(state, amount_egp=1).result["error"] == "limit_exceeded"


def test_transfers_on_other_days_do_not_count_toward_the_limit() -> None:
    state = new_state(
        "banking",
        initial(),
        user_identity=IDENTITY,
        now=datetime(2026, 11, 4, 22, 30, tzinfo=UTC),  # 00:30 on 5 Nov in Cairo
    )
    assert isinstance(state, BankingState)
    assert state.today == "2026-11-05"
    assert send(state, amount_egp=50_000).mutated


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"from_account_id": "acc_404"}, "not_found"),
        ({"from_account_id": "acc_7", "to_account_id": "acc_1"}, "not_owner"),
        ({"to_account_id": "acc_1"}, "same_account"),
        ({"to_account_id": "acc_7"}, "not_beneficiary"),
        ({"to_account_id": "acc_404"}, "not_found"),
        ({"from_account_id": "acc_2", "amount_egp": 2_000}, "insufficient_funds"),
    ],
)
def test_transfer_errors_leave_state_unchanged(overrides: dict[str, Any], error: str) -> None:
    state = make()
    assert_rejected(state, send(state, **overrides), error)


@pytest.mark.parametrize("amount", [0, -5, "500", 500.5, True])
def test_transfer_amount_must_be_a_positive_integer(amount: object) -> None:
    state = make()
    record = send(state, amount_egp=amount)
    assert record.result["error"] == "invalid_arguments"
    assert not record.call_valid and not record.attempted_write and not record.mutated


def test_block_card() -> None:
    state = make()
    record = call(state, "block_card", card_last4="4821", reason="stolen")
    assert record.result == {"card_last4": "4821", "status": "blocked", "reason": "stolen"}
    assert record.mutated and state.cards[0].block_reason == "stolen"
    again = call(state, "block_card", card_last4="4821", reason="lost")
    assert again.result == {"error": "already_blocked"}
    assert again.attempted_write and not again.mutated


@pytest.mark.parametrize(("last4", "error"), [("1234", "not_owner"), ("9999", "not_found")])
def test_block_card_errors(last4: str, error: str) -> None:
    state = make()
    assert_rejected(state, call(state, "block_card", card_last4=last4, reason="fraud"), error)


def test_block_card_reason_enum_and_ascii_digits() -> None:
    state = make()
    wrong = call(state, "block_card", card_last4="4821", reason="broken")
    assert wrong.result["detail"] == [
        {"code": "literal_error", "field": "reason", "allowed": ["lost", "stolen", "fraud"]}
    ]
    indic = call(state, "block_card", card_last4="٤٨٢١", reason="lost")
    assert not indic.call_valid
    assert indic.validity_flags == ["schema_invalid", "non_ascii_digits"]


def test_banking_state_needs_a_date() -> None:
    with pytest.raises(ValueError, match="now"):
        new_state("banking", initial(), user_identity=IDENTITY)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["accounts"].append(dict(d["accounts"][0])),
        lambda d: d["cards"].append({"last4": "4821", "account_id": "acc_2"}),
        lambda d: d["cards"].append({"last4": "5555", "account_id": "acc_404"}),
        lambda d: d["transactions"].append(dict(d["transactions"][0])),
        lambda d: [a.update(owner_id="c_9") for a in d["accounts"]],
        lambda d: d["accounts"][0].update(balance_piastres="lots"),
    ],
)
def test_state_validation_rejects_inconsistent_authoring(mutate: Any) -> None:
    data = initial()
    mutate(data)
    with pytest.raises(ValidationError):
        make(data)
