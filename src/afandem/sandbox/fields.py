"""Annotated field types shared by state models and tool arguments.

Structured fields (ids, dates, times, phones, card digits) only accept ASCII digits: a pattern of
`[0-9]`, never `\\d`, which would also match Arabic-Indic digits.
"""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from afandem.sandbox.clock import parse_date

ID_PATTERN = r"^[A-Za-z0-9_.\-]{1,64}$"
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
TIME_PATTERN = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"
E164_EG_MOBILE = r"^\+201[0125][0-9]{8}$"
PHONE_ARG_PATTERN = r"^\+?[0-9][0-9 \-]{7,18}$"


def _real_date(value: str) -> str:
    parse_date(value)
    return value


Id = Annotated[str, Field(pattern=ID_PATTERN)]
IsoDate = Annotated[
    str, Field(pattern=DATE_PATTERN, description="YYYY-MM-DD"), AfterValidator(_real_date)
]
Hhmm = Annotated[str, Field(pattern=TIME_PATTERN, description="HH:MM, 24-hour")]
E164 = Annotated[str, Field(pattern=E164_EG_MOBILE)]
PhoneArg = Annotated[str, Field(pattern=PHONE_ARG_PATTERN, description="Egyptian mobile number")]
PersonName = Annotated[str, Field(min_length=1, max_length=120)]
Weekday = Literal["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]


class StateModel(BaseModel):
    """Base for sandbox state records: unknown keys in authored state are errors."""

    model_config = ConfigDict(extra="forbid")


class Args(BaseModel):
    """Base for tool arguments: unknown keys are invalid and nothing is coerced.

    `strict=True` keeps `"500"` from passing as an integer and `true` from passing as `1`.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
