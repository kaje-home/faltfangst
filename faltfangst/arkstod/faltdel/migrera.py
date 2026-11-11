"""Bygger ut ett raa lansuttag sa att det gaar att arbeta i.

RAA:s uttag ar normaliserat: geometritabellerna bar bara fid, geometri,
lamning_uuid och geometrinummer, medan alla attribut ligger i den centrala
`lamning`-tabellen. Det ar en riktig modell for utbyte och en obekvam modell
for faltarbete -- ett formular kan inte redigera falt som ligger i en annan
tabell utan relationer, och relationer i QGIS ar tyngre an de ser ut.

Losningen ar densamma som verktygets forsta version valde: kopiera
lamningens attribut rakt in i geometritabellerna. Vyer plus triggrar provades
da och fungerade inte utan SpatiaLite.

Tva saker skiljer den har versionen fran den forsta:

Faltlistan harleds ur `lamning`s eget schema i stallet for att skrivas av. Far
uttaget en ny kolumn foljer den med av sig sjalv, i stallet for att tyst
utebli tills nagon marker det.

Rtree-triggrarna tas bort under bulkuppdateringen och laggs tillbaka efterat.
Det ar inte for att komma runt SpatiaLite -- geometri.py loser det -- utan for
att de annars utvarderas en gaang per rad utan att geometrin nagonsin andras.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from arkstod.faltdel.falt import ALLA_EGNA, sakerstall_kolumner
from arkstod.faltdel.geometri import registrera as registrera_geometrifunktioner

# Attributtabellen och dess nyckel. RAA kallar kolumnen `uuid`, medan
# geometritabellerna kallar samma varde `lamning_uuid`.
ATTRIBUTTABELL = "lamning"
ATTRIBUTNYCKEL = "uuid"
GEOMETRINYCKEL = "lamning_uuid"

# Kolumner som aldrig kopieras: de hor till tabellen, inte till lamningen.
_HOPPAS_OVER = {"fid", ATTRIBUTNYCKEL, "geometri", "geom", "geometry"}

# Uttaget ar normaliserat over tre geometritabeller. Uttaget bar ocksa en
# lagesosakerhetstabell med samma nyckel, men den ar inget faltformularet
# redigerar -- och att bygga ut den kostade 30 MB pa Blekinge utan att nagon
# fick nagot for det. Ange `tabeller` for att valja annat.
GEOMETRITABELLER: tuple[str, ...] = ("point", "linestring", "polygon")


@dataclass
class Migreringsrapport:
    tabeller: dict[str, int] = field(default_factory=dict)
    kopierade_falt: list[str] = field(default_factory=list)
    egna_kolumner: dict[str, list[str]] = field(default_factory=dict)
    redan_migrerat: bool = False


def _kolumner(anslutning: sqlite3.Connection, tabell: str) -> list[str]:
    return [
        rad[1] for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")').fetchall()
    ]


def _kolumntyper(anslutning: sqlite3.Connection, tabell: str) -> dict[str, str]:
    return {
        rad[1]: rad[2] or "TEXT"
        for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")').fetchall()
    }


def _geometritabeller(anslutning: sqlite3.Connection) -> list[str]:
    namn = [
        rad[0]
        for rad in anslutning.execute(
            "SELECT c.table_name FROM gpkg_contents c"
            " JOIN sqlite_master m ON m.name = c.table_name AND m.type = 'table'"
            " WHERE c.data_type = 'features'"
        ).fetchall()
    ]
    return [
        tabell for tabell in namn if GEOMETRINYCKEL in _kolumner(anslutning, tabell)
    ]


def _rtree_triggrar(
    anslutning: sqlite3.Connection, tabell: str
) -> list[tuple[str, str]]:
    return [
        (rad[0], rad[1])
        for rad in anslutning.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
            " AND tbl_name = ? AND name LIKE 'rtree_%'",
            (tabell,),
        ).fetchall()
        if rad[1]
    ]


def migrera(
    gpkg: Path | str, tabeller: tuple[str, ...] | None = None
) -> Migreringsrapport:
    """Kopierar lamningens attribut in i geometritabellerna. Idempotent."""
    gpkg = Path(gpkg)
    if not gpkg.exists():
        raise FileNotFoundError(f"ingen GPKG pa {gpkg}")

    anslutning = sqlite3.connect(gpkg)
    registrera_geometrifunktioner(anslutning)
    rapport = Migreringsrapport()
    try:
        if ATTRIBUTTABELL not in _kolumner_i_databasen(anslutning):
            raise ValueError(
                f"{gpkg.name} har ingen {ATTRIBUTTABELL}-tabell — är det ett"
                " lämningsuttag från RAÄ?"
            )

        typer = _kolumntyper(anslutning, ATTRIBUTTABELL)
        falt = [namn for namn in typer if namn not in _HOPPAS_OVER]
        rapport.kopierade_falt = falt

        valda = [
            tabell
            for tabell in _geometritabeller(anslutning)
            if tabell in (tabeller or GEOMETRITABELLER)
        ]
        for tabell in valda:
            rapport.tabeller[tabell] = _migrera_tabell(anslutning, tabell, falt, typer)

        rapport.egna_kolumner = sakerstall_kolumner(anslutning, valda, ALLA_EGNA)
        anslutning.commit()
    finally:
        anslutning.close()
    return rapport


def _kolumner_i_databasen(anslutning: sqlite3.Connection) -> set[str]:
    return {
        rad[0]
        for rad in anslutning.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _migrera_tabell(
    anslutning: sqlite3.Connection,
    tabell: str,
    falt: list[str],
    typer: dict[str, str],
) -> int:
    befintliga = set(_kolumner(anslutning, tabell))
    for namn in falt:
        if namn not in befintliga:
            anslutning.execute(
                f'ALTER TABLE "{tabell}" ADD COLUMN "{namn}" {typer[namn]}'
            )

    # Triggrarna bort under bulkuppdateringen. Geometrin ror sig inte, sa
    # rtree behover inte skrivas om -- men varje WHEN-sats skulle utvarderas
    # en gaang per rad.
    triggrar = _rtree_triggrar(anslutning, tabell)
    for namn, _sql in triggrar:
        anslutning.execute(f'DROP TRIGGER IF EXISTS "{namn}"')

    try:
        satser = ", ".join(
            f'"{namn}" = (SELECT a."{namn}" FROM "{ATTRIBUTTABELL}" a'
            f' WHERE a."{ATTRIBUTNYCKEL}" = "{tabell}"."{GEOMETRINYCKEL}")'
            for namn in falt
        )
        markor = anslutning.execute(f'UPDATE "{tabell}" SET {satser}')
        antal = markor.rowcount

        # Fornsokslanken gors klickbar. Idempotent: en redan omgjord lank ror
        # sig inte, sa en andra korning lagger inte lank i lank.
        if "url" in falt:
            anslutning.execute(
                f'UPDATE "{tabell}" SET url ='
                " '<a href=\"' || url || '\">Öppna i Fornsök</a>'"
                " WHERE url IS NOT NULL AND url <> '' AND url NOT LIKE '<a%'"
            )
    finally:
        for _namn, sql in triggrar:
            anslutning.execute(sql)

    return antal
