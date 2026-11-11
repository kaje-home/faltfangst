"""Tva lansuttag till en arbetsfil, nar arbetet gaar over lansgransen.

RAA lamnar ut lamningarna per lan. Ett arbete gor det inte: en kraftledning
som gaar fran Jamtland in i Vasternorrland ar ett arbete, och inventeraren
ska se registrets lamningar pa bada sidor om gransen i samma karta.

Sammanfogningen sker i RAA:s egen form, fore migreringen. Da gaar resten av
uttaget -- migrering, uppslag, avtryck, typlista -- over en enda fil som om
den kommit sa fran borjan, och ingenting efter det behover veta att den
bestod av tva.

Lamningar pa sjalva gransen star redan i bada uttagen; `lan`-kolumnen bar da
bada namnen, kommaseparerat. De tas med en gang. Nyckeln ar lamningens uuid,
och for egenskaper och ingaende lamningar registrets eget id -- bada ar
nationella, sa samma lamning har samma nyckel i vilket lans uttag den an
star.

Tabellerna heter lika i alla lan utom lagesosakerheten, som bar lanets namn:
`lämningar_län_jämtland_lägesosäkerhet`. Den paras ihop pa det som kommer
efter lansnamnet. Vyerna fogas inte -- de ar fragor mot tabellerna och
foljer med av sig sjalva.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from arkstod import lan as lansmodul
from arkstod.faltdel.geometri import registrera as registrera_geometrifunktioner

_LANSPREFIX = "lämningar_län_"


@dataclass
class Fogningsrapport:
    """Vad ett grannlan tillforde."""

    tillagda: dict[str, int] = field(default_factory=dict)
    # Lamningar som redan fanns i det forsta uttaget -- de pa gransen.
    gemensamma: int = 0
    # Tabeller i grannlanets uttag utan motsvarighet i det forsta.
    utelamnade: list[str] = field(default_factory=list)

    @property
    def lamningar(self) -> int:
        return self.tillagda.get("lamning", 0)


def _parningsnamn(tabell: str) -> str:
    """Tabellnamnet med lanets namn bortplockat, for att para ihop lan."""
    if not tabell.startswith(_LANSPREFIX):
        return tabell
    resten = tabell[len(_LANSPREFIX):]
    for lan in sorted(lansmodul.LAN, key=len, reverse=True):
        for stavning in (lan, lan.replace(" ", "_")):
            if resten.startswith(stavning + "_"):
                return _LANSPREFIX + "*_" + resten[len(stavning) + 1:]
    return tabell


def _datatabeller(anslutning: sqlite3.Connection, schema: str) -> list[str]:
    """Tabellerna med registrets data -- inte vyerna, inte GPKG:ns egna."""
    return [
        rad[0]
        for rad in anslutning.execute(
            f"SELECT c.table_name FROM {schema}.gpkg_contents c"
            f" JOIN {schema}.sqlite_master m"
            "  ON m.name = c.table_name AND m.type = 'table'"
            " WHERE c.data_type IN ('features', 'attributes')"
            " ORDER BY c.table_name"
        ).fetchall()
    ]


def _kolumner(anslutning: sqlite3.Connection, schema: str, tabell: str) -> list[str]:
    return [
        rad[1]
        for rad in anslutning.execute(
            f'PRAGMA {schema}.table_info("{tabell}")'
        ).fetchall()
    ]


def _vidga_utbredningen(
    anslutning: sqlite3.Connection, tabell: str, maltabell: str
) -> None:
    """Utbredningen i gpkg_contents ar det QGIS zoomar till.

    Den ska tacka bada lanen, inte bara det forsta. Raknas har i stallet for
    med UPDATE ... FROM, som SQLite forst fick i 3.33 -- och vilken version
    QGIS bar med sig ar inte vart att gissa om.
    """
    fraga = "SELECT min_x, min_y, max_x, max_y FROM {}.gpkg_contents WHERE table_name = ?"
    egen = anslutning.execute(fraga.format("main"), (maltabell,)).fetchone()
    grannens = anslutning.execute(fraga.format("granne"), (tabell,)).fetchone()
    if not egen or not grannens:
        return
    varden = []
    for index, valj in enumerate((min, min, max, max)):
        kandidater = [v for v in (egen[index], grannens[index]) if v is not None]
        varden.append(valj(kandidater) if kandidater else None)
    anslutning.execute(
        "UPDATE main.gpkg_contents SET min_x = ?, min_y = ?, max_x = ?, max_y = ?"
        " WHERE table_name = ?",
        (*varden, maltabell),
    )


def foga_in(mal: Path | str, kalla: Path | str) -> Fogningsrapport:
    """Lagger grannlanets lamningar i `mal`. `kalla` lamnas orord.

    Bada ska vara RAA:s uttag som de kom, fore migreringen.
    """
    mal, kalla = Path(mal), Path(kalla)
    anslutning = sqlite3.connect(mal)
    # Rtree-triggrarna anvander ST_MinX och de andra. Utan dem gaar
    # insattningen inte att gora, och med dem halls det rumsliga indexet
    # i takt -- QGIS hittar grannlanets lamningar pa kartan.
    registrera_geometrifunktioner(anslutning)
    rapport = Fogningsrapport()
    try:
        anslutning.execute("ATTACH DATABASE ? AS granne", (str(kalla),))

        mina = {_parningsnamn(t): t for t in _datatabeller(anslutning, "main")}
        if "lamning" not in mina:
            raise ValueError(f"{mal.name} har ingen lamning-tabell")

        # Vilka lamningar som redan finns, fore insattningen. Annars skulle
        # grannlanets egna rader i lamning sla ut dess geometrier.
        anslutning.execute(
            "CREATE TEMP TABLE befintliga AS SELECT uuid FROM main.lamning"
        )
        anslutning.execute("CREATE INDEX temp.befintliga_uuid ON befintliga(uuid)")

        for tabell in _datatabeller(anslutning, "granne"):
            maltabell = mina.get(_parningsnamn(tabell))
            if maltabell is None:
                rapport.utelamnade.append(tabell)
                continue

            egna = _kolumner(anslutning, "main", maltabell)
            gemensamma = [
                k for k in _kolumner(anslutning, "granne", tabell)
                if k in egna and k != "fid"
            ]
            lista = ", ".join(f'"{k}"' for k in gemensamma)

            if "uuid" in gemensamma:
                villkor = "uuid NOT IN (SELECT uuid FROM befintliga)"
            elif "id" in gemensamma:
                villkor = (
                    f'id NOT IN (SELECT id FROM main."{maltabell}"'
                    " WHERE id IS NOT NULL)"
                )
            elif "lamning_uuid" in gemensamma:
                villkor = "lamning_uuid NOT IN (SELECT uuid FROM befintliga)"
            else:
                villkor = "1"

            markor = anslutning.execute(
                f'INSERT INTO main."{maltabell}" ({lista})'
                f' SELECT {lista} FROM granne."{tabell}" WHERE {villkor}'
            )
            rapport.tillagda[maltabell] = markor.rowcount

            if "uuid" in gemensamma:
                rapport.gemensamma = anslutning.execute(
                    f'SELECT count(*) FROM granne."{tabell}"'
                    " WHERE uuid IN (SELECT uuid FROM befintliga)"
                ).fetchone()[0]

            _vidga_utbredningen(anslutning, tabell, maltabell)

        anslutning.commit()
        anslutning.execute("DROP TABLE temp.befintliga")
        anslutning.execute("DETACH DATABASE granne")
    finally:
        anslutning.close()
    return rapport
