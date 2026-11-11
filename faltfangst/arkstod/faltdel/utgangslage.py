"""Ett avtryck av uttaget som det saag ut nar arbetsmappen skapades.

Leveranslistan ska innehalla det man gjort under jobbet: nya lamningar och
reviderade. Fragan ar hur man vet vilka de ar.

Kvallsvyn svarade "de rader dar nagot av verktygets egna falt ar ifyllt", och
det svaret ar fel. En revidering ror oftast bara `beskrivning`, som ar RAA:s
kolumn -- da raknas raden inte som rord, och just den lamning man skrivit om
faller ur listan. Provat: skriv om en beskrivning och kvallsvyn ser ingenting;
fyll i en kommentar pa samma rad och samma anmarkning dyker upp.

Har jamfors i stallet mot uttaget. Nar mappen skapas skrivs ett avtryck per
lamning -- en hash av de falt som gaar att andra, geometrin medraknad. Vid
leverans raknas avtrycken om: det som skiljer sig ar reviderat, det som saknas
i tabellen ar nytt. Da kan ingen andring falla ur, oavsett vilket falt den
gjordes i.

Avtrycket ar en hash och inte en kopia. En kopia av 35 000 lamningars text
hade dubblat filen; hashen kostar 32 byte per rad och svarar pa den enda
fragan som stalls: har det har andrats?

Ett falt sparas anda i klartext: `skadestatus`. Se BEVARADE_FALT.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

TABELL = "ark_utgangslage"

# Falten som gaar att andra i formularet och som betyder nagot vid leverans.
# Geometrin laggs till separat -- den ar en blob och hanteras for sig.
#
# `ovrigt` star med trots att det ar en egen anteckning som inte levereras:
# har man skrivit en minnesanteckning pa en lamning har man arbetat med den,
# och da ska den synas i listan.
AVTRYCKSFALT: tuple[str, ...] = (
    "lamningstyp",
    "beskrivning",
    "antikvariskbedomning",
    "antikvariskbedomning_motivering",
    "aktualitetstatus",
    "skadestatus",
    "Skadebesk",
    "undersokningsstatus",
    "placering",
    "orientering",
    "terrang",
    "veg",
    "tradition",
    "lamningsnamn",
    "Kommentar",
    "ovrigt",
    "Granskningsdatum",
    "matmet",
    "Karta",
    "TID",
)

# Falt vars tidigare varde sparas i klartext, inte bara i hashen.
#
# `skadestatus` ar RAA:s eget falt, medan `Skadebesk` ar vart -- RAA:s oppna
# uttag bar ingen skadebeskrivning alls. Foljden: varje lamning RAA markt som
# skadad kommer in i arbetsfilen med status men utan beskrivning, och regeln
# "atverkan kraver en beskrivning" slog till pa hela lanet.
#
# Anmarkningen var dessutom osann. Beskrivningen finns hos RAA -- den syns i
# Fornsok -- den foljer bara inte med i uttaget. Verktyget sa alltsa att en
# uppgift saknades som inte saknades.
#
# Kravet hor till det jobbet sjalvt registrerar. For att veta det racker inte
# "har raden andrats" utan "sa den sa har forut", och darfor det haer.
BEVARADE_FALT: tuple[str, ...] = ("skadestatus",)


@dataclass
class Utgangslagesrapport:
    tabeller: dict[str, int] = field(default_factory=dict)

    @property
    def antal(self) -> int:
        return sum(self.tabeller.values())


def _kolumner(anslutning: sqlite3.Connection, tabell: str) -> set[str]:
    return {
        rad[1]
        for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")').fetchall()
    }


def geometritabeller(anslutning: sqlite3.Connection) -> list[str]:
    """RAA:s egna lager i uttaget som bar en lamningstyp."""
    namn = [
        rad[0]
        for rad in anslutning.execute(
            "SELECT c.table_name FROM gpkg_contents c"
            " JOIN sqlite_master m ON m.name = c.table_name AND m.type = 'table'"
            " WHERE c.data_type = 'features' AND c.table_name NOT LIKE 'ark_%'"
        ).fetchall()
    ]
    return [
        tabell for tabell in namn if "lamningstyp" in _kolumner(anslutning, tabell)
    ]


def avtryck(rad: dict, kolumner: list[str], geometri: bytes | None) -> str:
    """Ett avtryck av radens andringsbara innehall.

    Vardena skiljs med ett tecken som inte kan sta i ett textfalt, sa att
    "ab" + "c" och "a" + "bc" inte ger samma avtryck.
    """
    hash_ = hashlib.sha256()
    for kolumn in kolumner:
        varde = rad.get(kolumn)
        hash_.update(b"\x00" if varde is None else str(varde).encode("utf-8"))
        hash_.update(b"\x1f")
    if geometri is not None:
        hash_.update(geometri)
    return hash_.hexdigest()


def _avtrycksfalt(kolumner: set[str]) -> list[str]:
    """Falten i AVTRYCKSFALT som tabellen faktiskt har, i fast ordning."""
    return [kolumn for kolumn in AVTRYCKSFALT if kolumn in kolumner]


def finns(anslutning: sqlite3.Connection) -> bool:
    """Om arbetsfilen bar ett avtryck alls.

    Fragan maste stallas om tabellen och inte om raderna: en tom
    geometritabell -- ett lan utan linjer, ett provuttag -- har inga avtryck
    utan att nagot ar fel.
    """
    return (
        anslutning.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            (TABELL,),
        ).fetchone()[0]
        == 1
    )


def las_bevarade(
    anslutning: sqlite3.Connection, tabell: str
) -> dict[int, dict[str, str]]:
    """Vad BEVARADE_FALT stod pa varje rad vid uttaget."""
    kolumner = ", ".join(f'"{namn}"' for namn in BEVARADE_FALT)
    try:
        rader = anslutning.execute(
            f'SELECT fid, {kolumner} FROM "{TABELL}" WHERE tabell = ?', (tabell,)
        ).fetchall()
    except sqlite3.OperationalError:
        # Ett avtryck skrivet innan faltet fanns. Da vet vi inte, och da ska
        # ingen regel latsas veta.
        return {}
    return {
        rad[0]: {namn: rad[i + 1] or "" for i, namn in enumerate(BEVARADE_FALT)}
        for rad in rader
    }


def las_avtryck(anslutning: sqlite3.Connection, tabell: str) -> dict[int, str]:
    """Radernas avtryck som de saag ut vid uttaget. Tom om tabellen saknas."""
    try:
        return {
            rad[0]: rad[1]
            for rad in anslutning.execute(
                f'SELECT fid, avtryck FROM "{TABELL}" WHERE tabell = ?', (tabell,)
            ).fetchall()
        }
    except sqlite3.OperationalError:
        return {}


def _bevarade_nu(
    anslutning: sqlite3.Connection, tabell: str
) -> dict[int, dict[str, str]]:
    """Vad BEVARADE_FALT star pa varje rad just nu."""
    kolumner = _kolumner(anslutning, tabell)
    falt = [namn for namn in BEVARADE_FALT if namn in kolumner]
    if not falt:
        return {}
    citerade = ", ".join(f'"{namn}"' for namn in falt)
    return {
        rad[0]: {namn: rad[i + 1] or "" for i, namn in enumerate(falt)}
        for rad in anslutning.execute(f'SELECT fid, {citerade} FROM "{tabell}"')
    }


def berakna(anslutning: sqlite3.Connection, tabell: str) -> dict[int, str]:
    """Radernas avtryck som de ser ut nu."""
    kolumner = _kolumner(anslutning, tabell)
    falt = _avtrycksfalt(kolumner)
    har_geometri = "geometri" in kolumner
    valda = ["fid", *falt] + (["geometri"] if har_geometri else [])
    citerade = ", ".join(f'"{kolumn}"' for kolumn in valda)

    anslutning.row_factory = sqlite3.Row
    resultat: dict[int, str] = {}
    for rad in anslutning.execute(f'SELECT {citerade} FROM "{tabell}"'):
        post = dict(rad)
        resultat[post["fid"]] = avtryck(
            post, falt, post.get("geometri") if har_geometri else None
        )
    return resultat


def skriv(gpkg: Path | str) -> Utgangslagesrapport:
    """Skriver avtrycket for hela uttaget. Kors nar arbetsmappen skapas."""
    anslutning = sqlite3.connect(gpkg)
    try:
        anslutning.execute(f'DROP TABLE IF EXISTS "{TABELL}"')
        anslutning.execute(
            f'CREATE TABLE "{TABELL}" ('
            " tabell TEXT NOT NULL,"
            " fid INTEGER NOT NULL,"
            " avtryck TEXT NOT NULL,"
            + "".join(f' "{namn}" TEXT,' for namn in BEVARADE_FALT)
            + " PRIMARY KEY (tabell, fid))"
        )
        bevarade_kolumner = "".join(f', "{namn}"' for namn in BEVARADE_FALT)
        platser = ", ".join("?" for _ in BEVARADE_FALT)
        rapport = Utgangslagesrapport()
        for tabell in geometritabeller(anslutning):
            avtrycken = berakna(anslutning, tabell)
            bevarade = _bevarade_nu(anslutning, tabell)
            anslutning.executemany(
                f'INSERT INTO "{TABELL}" (tabell, fid, avtryck{bevarade_kolumner})'
                f" VALUES (?, ?, ?, {platser})",
                [
                    (tabell, fid, varde)
                    + tuple(
                        bevarade.get(fid, {}).get(namn, "") for namn in BEVARADE_FALT
                    )
                    for fid, varde in avtrycken.items()
                ],
            )
            rapport.tabeller[tabell] = len(avtrycken)
        anslutning.commit()
        return rapport
    finally:
        anslutning.close()
