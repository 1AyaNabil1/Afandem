from dataclasses import dataclass, field

import pytest

from afandem.sandbox.names import (
    Collision,
    alias_collisions,
    fold_arabic,
    fold_latin,
    lookup,
    match_name,
    name_key,
    name_tokens,
    normalise_phone,
    phone_collisions,
    unmatchable_aliases,
)

RLM, LRM, ZWNJ, TATWEEL, FATHA, DAMMA = (
    chr(c) for c in (0x200F, 0x200E, 0x200C, 0x640, 0x64E, 0x64F)
)
PERSIAN_YEH, PERSIAN_KAF, LAM_ALEF_LIGATURE = chr(0x6CC), chr(0x6A9), chr(0xFEFB)


@dataclass
class Person:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    phone: str | None = None


MONA = Person(
    "p_17",
    "منى محمود عبد الحليم",
    [
        "منى محمود",
        "مني محمود عبدالحليم",
        "Mona Mahmoud",
        "Mona Mahmoud Abdel Halim",
        "mona ma7moud",
    ],
    "+201000000017",
)
MOHAMED = Person(
    "p_21",
    "محمد أحمد عبد الرحمن السيد",
    ["Mohamed Ahmed Abdelrahman El Sayed"],
    "+201000000021",
)
HEBA = Person("d_2", "د. هبة السيد", ["هبه السيد", "الدكتورة هبة", "Dr. Heba El Sayed"])
RECORDS = [MONA, MOHAMED]


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("أحمد", "احمد"),
        ("إسماعيل", "اسماعيل"),
        ("آمال", "امال"),
        ("منى", "مني"),
        ("فاطمة", "فاطمه"),
        (f"ي{PERSIAN_YEH}", "يي"),
        (f"{PERSIAN_KAF}ريم", "كريم"),
        (f"م{DAMMA}ن{FATHA}ى", "مني"),
        (f"محـ{TATWEEL}ـمود", "محمود"),
        (f"{RLM}منى{ZWNJ} محمود{LRM}", "مني محمود"),
        ("عبد الرحمن", "عبدالرحمن"),
        ("عبد  الحليم", "عبدالحليم"),
        (f"{LAM_ALEF_LIGATURE}", "لا"),
    ],
)
def test_arabic_folding(a: str, b: str) -> None:
    assert fold_arabic(a) == fold_arabic(b) == b


@pytest.mark.parametrize(
    "variants",
    [
        ("Mohamed", "Mohammed", "Muhammad", "Mohammad", "MOHAMED"),
        ("Ahmed", "Ahmad"),
        ("Abdelrahman", "Abd El Rahman", "Abdul Rahman", "Abd-El-Rahman", "Abdel Rahman"),
        ("Youssef", "Yousef"),
        ("Khaled", "Khalid"),
        ("Fatma", "Fatima"),
        ("Nour", "Noor"),
        ("Mahmoud", "Mahmood"),
        ("Abdel Halim", "Abdelhalim", "abdel-halim"),
        ("Heba El Sayed", "heba elsayed", "Heba Al Sayed"),
    ],
)
def test_latin_folding_clusters(variants: tuple[str, ...]) -> None:
    assert len({fold_latin(v) for v in variants}) == 1


def test_latin_folding_keeps_different_names_apart() -> None:
    assert fold_latin("Mona Mahmoud") == "monamahmoud"
    assert fold_latin("Mona Mahmoud") != fold_latin("Heba Mahmoud")
    assert fold_latin("Ahmed") != fold_latin("Mahmoud")


@pytest.mark.parametrize(
    ("name", "count"),
    [
        ("منى محمود عبد الحليم", 3),
        ("هبة السيد", 2),
        ("Heba El Sayed", 2),
        ("عبد الرحمن", 1),
        ("Abd El Rahman", 1),
        ("Dr. Heba", 2),
        ("منى، محمود", 2),
    ],
)
def test_name_token_counts(name: str, count: int) -> None:
    assert len(name_tokens(name)) == count


def test_name_key_is_space_insensitive_across_forms() -> None:
    assert name_key("منى محمود عبد الحليم") == name_key("مني محمود عبدالحليم")
    assert name_key("Mona Mahmoud Abdel Halim") == name_key("mona mahmood abdel-halim")


@pytest.mark.parametrize(
    "phone",
    [
        "01000000017",
        "+20 100 000 0017",
        "+201000000017",
        "0020 100 000 0017",
        "20 1000000017",
        "0100-000-0017",
        "٠١٠٠٠٠٠٠٠١٧",
        "۰۱۰۰۰۰۰۰۰۱۷",
        f"{RLM}٠١٠٠٠٠٠٠٠١٧{LRM}",
        "(010) 0000 0017",
    ],
)
def test_phone_forms_normalise_to_e164(phone: str) -> None:
    assert normalise_phone(phone) == "+201000000017"


@pytest.mark.parametrize(
    "phone",
    [
        "0225551234",
        "1000000017",
        "01300000017",
        "010000000171",
        "+20010000000017",
        "",
        "0100000001",
    ],
)
def test_phone_forms_rejected(phone: str) -> None:
    assert normalise_phone(phone) is None


@pytest.mark.parametrize(
    "phone", ["01000000017", "٠١٠٠٠٠٠٠٠١٧", "+20 100 000 0017", "0020 1000000017"]
)
def test_lookup_by_phone(phone: str) -> None:
    assert lookup(RECORDS, phone=phone) == "p_17"


@pytest.mark.parametrize(
    "name",
    [
        "منى محمود",
        "منى محمود عبد الحليم",
        "مني محمود عبدالحليم",
        "مُنى محمود",
        "Mona Mahmoud",
        "mona mahmood abdel-halim",
        "MONA MAHMOUD ABDELHALIM",
        "mona ma7moud",
    ],
)
def test_lookup_by_name_in_both_scripts(name: str) -> None:
    assert lookup(RECORDS, name=name) == "p_17"


def test_lookup_by_name_prefix_of_a_longer_form() -> None:
    assert lookup(RECORDS, name="محمد أحمد") == "p_21"
    assert lookup(RECORDS, name="Muhammad Ahmad Abd El Rahman") == "p_21"


def test_lookup_phone_wins_over_name() -> None:
    assert lookup(RECORDS, name="Mona Mahmoud", phone="01000000021") == "p_21"


def test_lookup_falls_back_to_name_when_phone_misses_or_is_malformed() -> None:
    assert lookup(RECORDS, name="Mona Mahmoud", phone="01000000099") == "p_17"
    assert lookup(RECORDS, name="Mona Mahmoud", phone="1000000017") == "p_17"


def test_lookup_not_found() -> None:
    assert lookup(RECORDS, name="Heba El Sayed") == {"error": "not_found"}
    assert lookup(RECORDS, name="منى") == {"error": "not_found"}  # one token is never enough
    assert lookup(RECORDS, phone="01000000099") == {"error": "not_found"}
    assert lookup(RECORDS) == {"error": "not_found"}


def test_lookup_ambiguous() -> None:
    other = Person("p_22", "منى محمود السيد", ["Mona Mahmoud El Sayed"], "+201000000022")
    records = [*RECORDS, other]
    assert lookup(records, name="منى محمود") == {"ambiguous": ["p_17", "p_22"]}
    assert lookup(records, name="Mona Mahmoud") == {"ambiguous": ["p_17", "p_22"]}
    assert lookup(records, name="منى محمود السيد") == "p_22"
    assert lookup(records, name="منى محمود", phone="01000000022") == "p_22"
    twin = Person("p_23", "x", [], "+201000000017")
    assert lookup([MONA, twin], phone="01000000017") == {"ambiguous": ["p_17", "p_23"]}


def test_match_name_on_doctors() -> None:
    assert match_name([HEBA], "الدكتورة هبة") == ["d_2"]
    assert match_name([HEBA], "Dr. Heba El Sayed") == ["d_2"]
    assert match_name([HEBA], "هبة") == []


def test_collision_lint() -> None:
    assert alias_collisions([MONA, MOHAMED, HEBA]) == []
    assert phone_collisions(RECORDS) == []
    other = Person("p_22", "منى محمود السيد", [], "0100 000 0017")
    # «منى محمود» (an alias of p_17) is a prefix of p_22's name; p_22 has no Latin alias.
    assert alias_collisions([MONA, other]) == [
        Collision("name", name_key("منى محمود"), ("p_17", "p_22"))
    ]
    assert phone_collisions([MONA, other]) == [
        Collision("phone", "+201000000017", ("p_17", "p_22"))
    ]


def test_unmatchable_aliases() -> None:
    lone = Person("p_30", "كريم", ["Karim", "أم كريم"])
    assert unmatchable_aliases([MONA, lone]) == [("p_30", "كريم"), ("p_30", "Karim")]
