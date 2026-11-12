"""Rattelser fran leveranslistan, in i arbetsfilen.

Ser man ett fel medan man sitter med Fornreg ska det ga att ratta dar. Vagen
tillbaka -- lamna sidan, oppna QGIS, leta fram lamningen, ratta i formularet,
skriva ut listan pa nytt och hitta tillbaka till sin plats -- ar en omvag per
fel, och den enda anledningen till att den fanns var att en HTML-sida inte kan
skriva i en GeoPackage.

Sidan far darfor ratta, och lamnar ifran sig en andringsfil. Det haer ar
andra halvan: den laeser filen och skriver in rattelserna.

**Rattelsen maste na arbetsfilen, inte bara Fornreg.** Rattar man bara i sidan
hamnar ratt text hos RAA medan arbetsfilen behaller felet -- och da sager
avtrycket fel saker om vad jobbet andrat, och felet ar tillbaka nasta gaang
listan skrivs ut.

Tre sparrar, och alla tre finns for att en andringsfil ar en fil som kan vara
gammal, hopblandad eller handredigerad:

* bara kolumnerna leveranslistan visar far skrivas
* det befintliga vardet maste vara det sidan sag. Har nagon andrat i QGIS
  under tiden hoppas rattelsen over och sags -- den som skrev sist ska inte
  vinna bara for att filen ligger i nedladdningsmappen
* ett rullistefalt far bara satt till ett varde som finns i listan, laest ur
  projektet. Ett statusvarde utanfor listan slaar sonder statusreglerna utan
  att nagot sager ifran
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from arkstod.faltdel.formular import QGIS_NULL

FILNAMN = "leveransandringar.json"


@dataclass(frozen=True)
class Andring:
    """En rattelse: ett falt i en lamning, fran ett varde till ett annat."""

    tabell: str
    fid: int
    kolumn: str
    fran: str
    till: str


@dataclass
class Rattelserapport:
    gpkg: Path
    skrivna: list[Andring] = field(default_factory=list)
    hoppade: list[tuple[Andring, str]] = field(default_factory=list)

    @property
    def antal(self) -> int:
        return len(self.skrivna)


class Andringsfil(Exception):
    """Filen gaar inte att lasa som en andringsfil."""


def las(fil: Path | str) -> list[Andring]:
    """Laeser andringsfilen sidan lamnat ifran sig."""
    fil = Path(fil)
    try:
        innehall = json.loads(fil.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as fel:
        raise Andringsfil(f"{fil.name} går inte att läsa: {fel}") from fel

    poster = innehall.get("andringar") if isinstance(innehall, dict) else None
    if not isinstance(poster, list):
        raise Andringsfil(
            f"{fil.name} ser inte ut som en ändringsfil från leveranslistan."
        )

    andringar = []
    for post in poster:
        try:
            andringar.append(
                Andring(
                    tabell=str(post["tabell"]),
                    fid=int(post["fid"]),
                    kolumn=str(post["kolumn"]),
                    fran=str(post.get("fran", "")),
                    till=str(post.get("till", "")),
                )
            )
        except (KeyError, TypeError, ValueError) as fel:
            raise Andringsfil(f"{fil.name}: en post saknar uppgifter ({fel})") from fel
    return andringar


def _kolumner() -> set[str]:
    """De kolumner leveranslistan visar -- och alltsa de enda som far skrivas."""
    from arkstod.faltdel.leverans import FORNREG_ORDNING

    return {falt.kolumn for falt in FORNREG_ORDNING}


def _listor(gpkg: Path) -> dict[str, list[str]]:
    """Rullistornas tillatna varden, ur projektet i samma mapp."""
    from arkstod.faltdel.formular import valjbara_varden

    for qgz in sorted(gpkg.parent.glob("*.qgz")):
        try:
            return valjbara_varden(qgz)
        except (OSError, ValueError):
            continue
    # Inget projekt bredvid: da finns inget facit, och da kontrolleras inte
    # heller nagot. Det ar arligare an att hitta pa en lista.
    return {}


def _finns_tabell(anslutning: sqlite3.Connection, tabell: str) -> bool:
    return bool(
        anslutning.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabell,)
        ).fetchone()
    )


def tillampa(gpkg: Path | str, andringar: list[Andring]) -> Rattelserapport:
    """Skriver in rattelserna i arbetsfilen. Hoppar over det som inte haller."""
    gpkg = Path(gpkg)
    rapport = Rattelserapport(gpkg)
    tillatna = _kolumner()
    listor = _listor(gpkg)

    anslutning = sqlite3.connect(gpkg)
    try:
        for andring in andringar:
            if andring.kolumn not in tillatna:
                rapport.hoppade.append(
                    (andring, "kolumnen står inte i leveranslistan")
                )
                continue
            if not _finns_tabell(anslutning, andring.tabell):
                rapport.hoppade.append((andring, "tabellen finns inte i arbetsfilen"))
                continue
            # QGIS platshaallare for "inget varde". En leveranslista skriven
            # fore 1.4.7 hade den som ett val i rullistan for lamningstyp, och
            # en sadan lista kan ligga kvar. Den skrivs aldrig, vad listorna
            # an sager och aven nar inget projekt finns att prova mot.
            if andring.till.strip() == QGIS_NULL:
                rapport.hoppade.append(
                    (andring, "värdet är QGIS platshållare för tomt, inget värde")
                )
                continue

            val = listor.get(andring.kolumn)
            if val and andring.till and andring.till not in val:
                rapport.hoppade.append(
                    (andring, f"”{andring.till}” finns inte i fältets lista")
                )
                continue

            rad = anslutning.execute(
                f'SELECT "{andring.kolumn}" FROM "{andring.tabell}" WHERE fid = ?',
                (andring.fid,),
            ).fetchone()
            if rad is None:
                rapport.hoppade.append((andring, "lämningen finns inte längre"))
                continue

            nuvarande = "" if rad[0] is None else str(rad[0])
            if nuvarande != andring.fran:
                rapport.hoppade.append(
                    (andring, "värdet har ändrats i arbetsfilen sedan listan skrevs")
                )
                continue
            if nuvarande == andring.till:
                rapport.hoppade.append((andring, "redan skrivet"))
                continue

            anslutning.execute(
                f'UPDATE "{andring.tabell}" SET "{andring.kolumn}" = ? WHERE fid = ?',
                (andring.till or None, andring.fid),
            )
            rapport.skrivna.append(andring)
        anslutning.commit()
    finally:
        anslutning.close()
    return rapport


def tillampa_fil(gpkg: Path | str, fil: Path | str) -> Rattelserapport:
    """Laeser andringsfilen och skriver in det som haller."""
    return tillampa(gpkg, las(fil))
