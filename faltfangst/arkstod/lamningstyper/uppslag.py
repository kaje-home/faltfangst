"""Uppslag i lamningstypsdatabasen. Deterministiskt, utan spraakmodell.

Ett uppslag returnerar hela posten: definition, kommentar och bedomningsregel
tillsammans. Regeln lamnar aldrig sitt uppslagsord -- det ar den kopplingen
som gor lagret palitligt, och den som gar forlorad om listan chunkas.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Kallstampel:
    """Vilken text uppslaget kommer ur."""

    filnamn: str
    listversion: str
    hamtdatum: str
    sha256: str

    def hanvisning(self, sida: int | None = None) -> str:
        sidangivelse = f", s. {sida}" if sida is not None else ""
        return (
            f"Lämningstypslistan {self.listversion}{sidangivelse} "
            f"(hämtad {self.hamtdatum})"
        )


@dataclass
class Uppslag:
    """En lamningstyp som den star i listan."""

    benamning: str
    sida: int
    definition: str
    kommentar: str
    bedomning: str
    sammansatt: bool
    kategorier: list[str] = field(default_factory=list)
    egenskapstyper: list[tuple[str, bool, list[str]]] = field(default_factory=list)
    ingaende_typer: list[str] = field(default_factory=list)
    jfr: list[str] = field(default_factory=list)
    avgransningar: list[str] = field(default_factory=list)


def oppna(databas: Path | str) -> sqlite3.Connection:
    anslutning = sqlite3.connect(databas)
    anslutning.execute("PRAGMA foreign_keys = ON")
    anslutning.row_factory = sqlite3.Row
    return anslutning


def kallstampel(anslutning: sqlite3.Connection) -> Kallstampel:
    rad = anslutning.execute(
        "SELECT filnamn, listversion, hamtdatum, sha256 FROM kalla WHERE id = 1"
    ).fetchone()
    return Kallstampel(*rad)


def benamningar(anslutning: sqlite3.Connection) -> list[str]:
    return [
        rad[0]
        for rad in anslutning.execute(
            "SELECT benamning FROM lamningstyp ORDER BY ordning"
        )
    ]


def normalisera(benamning: str) -> str:
    """Gor tva skrivningar av samma benamning jamforbara.

    Kulturmiljoregistret och Lamningstypslistan stavar inte lika. Listan satter
    tankstreck i "Grav – uppgift om typ saknas", registret bindestreck. Det ar
    41 lamningar i Jamtland som inte skulle hitta sin regel, och felet syns
    inte: en value relation som inte matchar ger ett tomt falt, inte ett fel.
    """
    tecken = {"–": "-", "—": "-", "‑": "-", " ": " "}
    for fran, till in tecken.items():
        benamning = benamning.replace(fran, till)
    return " ".join(benamning.split()).casefold()


def slaupp(anslutning: sqlite3.Connection, benamning: str) -> Uppslag | None:
    """Hela posten for en lamningstyp, eller None om benamningen inte finns.

    Exakt traff forst; darefter en jamforelse som taal registrets stavning.
    """
    rad = anslutning.execute(
        "SELECT benamning, sida, definition, kommentar, bedomning, sammansatt"
        " FROM lamningstyp WHERE benamning = ?",
        (benamning,),
    ).fetchone()
    if rad is None:
        sokt = normalisera(benamning)
        for kandidat in benamningar(anslutning):
            if normalisera(kandidat) == sokt:
                return slaupp(anslutning, kandidat)
        return None

    uppslag = Uppslag(
        benamning=rad["benamning"],
        sida=rad["sida"],
        definition=rad["definition"],
        kommentar=rad["kommentar"],
        bedomning=rad["bedomning"],
        sammansatt=bool(rad["sammansatt"]),
        kategorier=[
            r[0]
            for r in anslutning.execute(
                "SELECT kategori FROM kategori WHERE benamning = ? ORDER BY kategori",
                (benamning,),
            )
        ],
        ingaende_typer=[
            r[0]
            for r in anslutning.execute(
                "SELECT ingaende FROM ingaende_typ WHERE sammansatt = ?"
                " ORDER BY ingaende",
                (benamning,),
            )
        ],
        avgransningar=[
            r[0]
            for r in anslutning.execute(
                "SELECT sats FROM avgransning WHERE benamning = ?", (benamning,)
            )
        ],
    )

    for etyp in anslutning.execute(
        "SELECT id, typnamn, flervard FROM egenskapstyp WHERE benamning = ?"
        " ORDER BY ordning",
        (benamning,),
    ).fetchall():
        varden = [
            r[0]
            for r in anslutning.execute(
                "SELECT varde FROM egenskapsvarde WHERE egenskapstyp = ?"
                " ORDER BY ordning",
                (etyp["id"],),
            )
        ]
        uppslag.egenskapstyper.append((etyp["typnamn"], bool(etyp["flervard"]), varden))

    # Forvaxlingsrisken gar at bada hallen: listan satter sitt Jfr dar den
    # tyckte det behovdes, men den som star i andra anden loper samma risk.
    uppslag.jfr = sorted(
        {
            rad[0]
            for rad in anslutning.execute(
                "SELECT till FROM jfr WHERE fran = ?"
                " UNION SELECT fran FROM jfr WHERE till = ?",
                (benamning, benamning),
            )
        }
    )
    return uppslag
