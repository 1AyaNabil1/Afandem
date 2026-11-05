"""Banking sandbox: state and the five tools.

Policy enforced here (the system prompt's policy block states it): the authenticated customer
may use their own accounts and cards; another customer's account only as the destination of a
transfer, and only when it is one of the customer's beneficiaries. A read or write of an account
or card the customer does not own returns `{"error": "not_owner"}`. Transfers above the daily
limit (every transfer out of the customer's accounts dated `today` counts) return
`limit_exceeded` and leave the state unchanged.

Money is stored as integer piastres; tool arguments take integer EGP; results show EGP.
"""

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from afandem.sandbox.clock import parse_date
from afandem.sandbox.fields import E164, Args, Id, IsoDate, PersonName, PhoneArg, StateModel
from afandem.sandbox.names import Collision, alias_collisions, lookup, phone_collisions
from afandem.sandbox.tools import JSONDict, ToolRegistry

PIASTRES_PER_EGP = 100
CARD_LAST4 = r"^[0-9]{4}$"
BlockReason = Literal["lost", "stolen", "fraud"]


def piastres_to_egp(piastres: int) -> int | float:
    """Whole pounds as an int, otherwise pounds with the piastres as decimals."""
    pounds, rest = divmod(piastres, PIASTRES_PER_EGP)
    return pounds if rest == 0 else piastres / PIASTRES_PER_EGP


def egp_to_piastres(egp: int) -> int:
    return egp * PIASTRES_PER_EGP


class Account(StateModel):
    id: Id
    owner_id: Id
    kind: Literal["current", "savings"] = "current"
    balance_piastres: int


class Card(StateModel):
    last4: str = Field(pattern=CARD_LAST4)
    account_id: Id
    status: Literal["active", "blocked"] = "active"
    block_reason: BlockReason | None = None


class Beneficiary(StateModel):
    """A saved transfer destination of one customer; looked up by name or phone."""

    owner_id: Id
    account_id: Id
    name: PersonName
    aliases: list[str] = Field(default_factory=list)
    phone: E164 | None = None
    bank: str | None = None

    @property
    def id(self) -> str:
        """Lookup id: the beneficiary's account id, which is what `transfer` takes."""
        return self.account_id


class Transaction(StateModel):
    id: Id
    date: IsoDate
    kind: Literal["transfer", "card", "deposit", "withdrawal", "fee"] = "transfer"
    from_account_id: Id | None = None
    to_account_id: Id | None = None
    amount_piastres: int = Field(gt=0)
    counterparty: str | None = None
    note: str | None = None


class BankingIdentity(StateModel):
    customer_id: Id
    phone: E164 | None = None


def _repeated(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    repeated: list[Any] = []
    for value in values:
        if value in seen:
            repeated.append(value)
        seen.add(value)
    return repeated


class BankingState(StateModel):
    user_identity: BankingIdentity
    today: IsoDate
    daily_limit_piastres: int = Field(gt=0)
    accounts: list[Account]
    cards: list[Card] = Field(default_factory=list)
    beneficiaries: list[Beneficiary] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)
    next_id: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        problems: list[str] = []
        for label, ids in (
            ("account", [a.id for a in self.accounts]),
            ("card", [c.last4 for c in self.cards]),
            ("beneficiary", [(b.owner_id, b.account_id) for b in self.beneficiaries]),
            ("transaction", [t.id for t in self.transactions]),
        ):
            problems += [f"duplicate {label} {dup}" for dup in _repeated(ids)]
        accounts = {a.id for a in self.accounts}
        problems += [
            f"card {c.last4} on unknown account" for c in self.cards if c.account_id not in accounts
        ]
        if not self.own_account_ids():
            problems.append(f"customer {self.user_identity.customer_id} owns no account")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def account(self, account_id: str) -> Account | None:
        return next((a for a in self.accounts if a.id == account_id), None)

    def own_account_ids(self) -> set[str]:
        return {a.id for a in self.accounts if a.owner_id == self.user_identity.customer_id}

    def owns(self, account_id: str) -> bool:
        return account_id in self.own_account_ids()

    def own_beneficiaries(self) -> list[Beneficiary]:
        return [b for b in self.beneficiaries if b.owner_id == self.user_identity.customer_id]

    def beneficiary(self, account_id: str) -> Beneficiary | None:
        """The customer's beneficiary with that account id."""
        return next((b for b in self.own_beneficiaries() if b.account_id == account_id), None)

    def transferred_today(self) -> int:
        """Piastres already transferred out of the customer's accounts on `today`."""
        own, today = self.own_account_ids(), parse_date(self.today)
        return sum(
            t.amount_piastres
            for t in self.transactions
            if t.kind == "transfer" and t.from_account_id in own and parse_date(t.date) == today
        )

    def identity_collisions(self) -> list[Collision]:
        """State-collision lint: one customer's beneficiaries the lookup cannot tell apart."""
        found: list[Collision] = []
        for owner in sorted({b.owner_id for b in self.beneficiaries}):
            mine = [b for b in self.beneficiaries if b.owner_id == owner]
            found += alias_collisions(mine) + phone_collisions(mine)
        return found


BANKING_TOOLS: ToolRegistry[BankingState] = ToolRegistry("banking", BankingState)


def _error(code: str, **extra: Any) -> JSONDict:
    return {"error": code, **extra}


def _compact(view: JSONDict) -> JSONDict:
    return {key: value for key, value in view.items() if value is not None}


def _own_account(state: BankingState, account_id: str) -> JSONDict | None:
    """The error for an account the customer may not use, else None."""
    if state.account(account_id) is None:
        return _error("not_found", field="account_id")
    if not state.owns(account_id):
        return _error("not_owner")
    return None


class GetBalanceArgs(Args):
    account_id: Id


@BANKING_TOOLS.tool(mutates=False)
def get_balance(state: BankingState, args: GetBalanceArgs) -> JSONDict:
    """Balance of one of the customer's accounts. Errors: not_found, not_owner."""
    if (problem := _own_account(state, args.account_id)) is not None:
        return problem
    account = state.account(args.account_id)
    assert account is not None
    return {
        "account_id": account.id,
        "kind": account.kind,
        "balance_egp": piastres_to_egp(account.balance_piastres),
    }


class ListTransactionsArgs(Args):
    account_id: Id
    date_from: IsoDate
    date_to: IsoDate


@BANKING_TOOLS.tool(mutates=False)
def list_transactions(state: BankingState, args: ListTransactionsArgs) -> JSONDict:
    """Transactions of one of the customer's accounts from date_from to date_to (inclusive).

    Returns {"transactions": [...]}. Errors: not_found, not_owner, invalid_range.
    """
    if (problem := _own_account(state, args.account_id)) is not None:
        return problem
    start, end = parse_date(args.date_from), parse_date(args.date_to)
    if start > end:
        return _error("invalid_range")
    rows = sorted(
        (
            t
            for t in state.transactions
            if args.account_id in (t.from_account_id, t.to_account_id)
            and start <= parse_date(t.date) <= end
        ),
        key=lambda t: (t.date, t.id),
    )
    return {
        "transactions": [
            _compact(
                {
                    "transaction_id": t.id,
                    "date": t.date,
                    "kind": t.kind,
                    "direction": "out" if t.from_account_id == args.account_id else "in",
                    "amount_egp": piastres_to_egp(t.amount_piastres),
                    "counterparty_account_id": (
                        t.to_account_id
                        if t.from_account_id == args.account_id
                        else t.from_account_id
                    ),
                    "counterparty": t.counterparty,
                    "note": t.note,
                }
            )
            for t in rows
        ]
    }


class ListBeneficiariesArgs(Args):
    account_id: Id
    name: PersonName | None = None
    phone: PhoneArg | None = None


def _beneficiary_view(b: Beneficiary) -> JSONDict:
    return _compact({"account_id": b.account_id, "name": b.name, "bank": b.bank})


@BANKING_TOOLS.tool(mutates=False)
def list_beneficiaries(state: BankingState, args: ListBeneficiariesArgs) -> JSONDict:
    """The customer's saved beneficiaries; with name (at least two name parts) or phone, only
    the matching one (the phone is matched first).

    Returns {"beneficiaries": [...]} or {"ambiguous": [account_id, ...]}. Errors: not_found,
    not_owner.
    """
    if (problem := _own_account(state, args.account_id)) is not None:
        return problem
    mine = state.own_beneficiaries()
    if args.name is None and args.phone is None:
        return {"beneficiaries": [_beneficiary_view(b) for b in mine]}
    found = lookup(mine, name=args.name, phone=args.phone)
    if not isinstance(found, str):
        return dict(found)
    return {"beneficiaries": [_beneficiary_view(b) for b in mine if b.account_id == found]}


class TransferArgs(Args):
    from_account_id: Id
    to_account_id: Id
    amount_egp: int = Field(gt=0, description="whole Egyptian pounds")
    note: str | None = Field(default=None, max_length=140)


@BANKING_TOOLS.tool(mutates=True)
def transfer(state: BankingState, args: TransferArgs) -> JSONDict:
    """Transfer from one of the customer's accounts to another of their accounts or to a
    beneficiary's account.

    Errors: not_found, not_owner, same_account, not_beneficiary, limit_exceeded,
    insufficient_funds.
    """
    source = state.account(args.from_account_id)
    if source is None:
        return _error("not_found", field="from_account_id")
    if not state.owns(source.id):
        return _error("not_owner")
    if args.to_account_id == source.id:
        return _error("same_account")
    amount = egp_to_piastres(args.amount_egp)
    if (problem := _destination_problem(state, args.to_account_id)) is not None:
        return problem
    if (problem := _funds_problem(state, source, amount)) is not None:
        return problem
    destination = state.account(args.to_account_id)
    beneficiary = state.beneficiary(args.to_account_id)
    transaction = Transaction(
        id=_new_transaction_id(state),
        date=state.today,
        kind="transfer",
        from_account_id=source.id,
        to_account_id=args.to_account_id,
        amount_piastres=amount,
        counterparty=beneficiary.name if beneficiary is not None else None,
        note=args.note,
    )
    source.balance_piastres -= amount
    if destination is not None:
        destination.balance_piastres += amount
    state.transactions.append(transaction)
    return {
        "transaction_id": transaction.id,
        "from_account_id": source.id,
        "to_account_id": args.to_account_id,
        "amount_egp": args.amount_egp,
        "balance_egp": piastres_to_egp(source.balance_piastres),
    }


def _destination_problem(state: BankingState, account_id: str) -> JSONDict | None:
    """An own account or one of the customer's beneficiaries is fine; else the error."""
    if state.owns(account_id) or state.beneficiary(account_id) is not None:
        return None
    if state.account(account_id) is None:
        return _error("not_found", field="to_account_id")
    return _error("not_beneficiary")


def _funds_problem(state: BankingState, source: Account, amount: int) -> JSONDict | None:
    """`limit_exceeded` (checked first) or `insufficient_funds`, else None."""
    spent = state.transferred_today()
    if spent + amount > state.daily_limit_piastres:
        return _error(
            "limit_exceeded",
            daily_limit_egp=piastres_to_egp(state.daily_limit_piastres),
            remaining_egp=piastres_to_egp(max(state.daily_limit_piastres - spent, 0)),
        )
    if source.balance_piastres < amount:
        return _error("insufficient_funds")
    return None


def _new_transaction_id(state: BankingState) -> str:
    existing = {t.id for t in state.transactions}
    while True:
        candidate = f"txn_{state.next_id:04d}"
        state.next_id += 1
        if candidate not in existing:
            return candidate


class BlockCardArgs(Args):
    card_last4: str = Field(pattern=CARD_LAST4, description="last four digits of the card")
    reason: BlockReason


@BANKING_TOOLS.tool(mutates=True)
def block_card(state: BankingState, args: BlockCardArgs) -> JSONDict:
    """Block one of the customer's cards. Errors: not_found, not_owner, already_blocked."""
    card = next((c for c in state.cards if c.last4 == args.card_last4), None)
    if card is None:
        return _error("not_found", field="card_last4")
    if not state.owns(card.account_id):
        return _error("not_owner")
    if card.status == "blocked":
        return _error("already_blocked")
    card.status, card.block_reason = "blocked", args.reason
    return {"card_last4": card.last4, "status": card.status, "reason": args.reason}
