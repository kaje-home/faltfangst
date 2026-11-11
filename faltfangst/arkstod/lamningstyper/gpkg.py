"""Skriver lamningstypsmodellen in i en lamningar-GPKG.

GPKG ar SQLite. Tabeller utan geometri kan skrivas rakt in och lasas som
vanliga lager i QGIS -- forutsatt att de registreras i `gpkg_contents` med
data_type `attributes`. Utan den raden finns tabellen i filen men syns inte i
lagerlistan, och det ar ett tyst fel av samma slag som XYZ-URI:er som
rapporteras giltiga men inte renderar.

Anvandningen ar value relation-falt i faltformularet: lamningstyp valjs ur
`ark_lamningstyp`, och egenskapsvardena filtreras pa vald typ. Darfor ar
`ark_egenskapsvarde` avsiktligt denormaliserad -- den bar bade benamning och
typnamn, sa att filteruttrycket klarar sig utan join. QGIS filteruttryck kan
inte joina.

Versionen skrivs in i `ark_modell`. I QGIS ser man tabellnamn, aldrig filnamn:
versionen maste vara synlig inifran.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from arkstod import lan as lansmodul
from arkstod.lamningstyper.uppslag import normalisera
from arkstod.faltdel import falt as faltmodul
from arkstod.faltdel import mattregel as mattregelmodul
from arkstod.faltdel import motivering as motiveringsmodul
from arkstod.faltdel.status import EJ_EGEN_UTBREDNING
from arkstod.tolkning.skikt import Skikt, las_ur_databas

# Prefixet haller vart isar fran RAA:s egna tabeller i uttaget.
PREFIX = "ark_"

TABELLER = (
    "modell",
    "lamningstyp",
    "kategori",
    "egenskapstyp",
    "egenskapsvarde",
    "ingaende_typ",
    "jfr",
    "avgransning",
    "uteslutning",
    "beskrivningstillagg",
    "formregel",
    "beskrivningsprincip",
    "beskrivningsexempel",
    "motivering",
    "anvisning",
)

# Tabeller verktyget har skapat forr men inte langre gor. De maste slappas
# aktivt: exporten droppar bara det den sjalv skriver, sa en borttagen tabell
# skulle annars ligga kvar i varje befintlig arbetsfil och visa sig som ett
# lager utan innehall. `mattregel` bar de harledda reglerna, `indikator`
# indikatorlistan.
UTGANGNA: tuple[str, ...] = ("mattregel", "indikator", "storningskalla")


@dataclass
class Exportrapport:
    gpkg: Path
    listversion: str
    hamtdatum: str
    modellversion: str
    rader: dict[str, int]
    tillagda_kolumner: dict[str, list[str]] = None  # type: ignore[assignment]
    lan: str = ""
    # Alla lan uttaget valdes for -- fler an ett nar arbetet gaar over
    # lansgransen. `lan` ar det forsta av dem.
    lanen: list[str] = None  # type: ignore[assignment]
    lansfordelning: dict[str, int] = None  # type: ignore[assignment]
    typer_i_bruk: int = 0
    oidentifierade: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.oidentifierade is None:
            self.oidentifierade = {}
        if self.lansfordelning is None:
            self.lansfordelning = {}
        if self.lanen is None:
            self.lanen = [self.lan] if self.lan else []
        if self.tillagda_kolumner is None:
            self.tillagda_kolumner = {}


def _tidsstampel() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _ar_gpkg(anslutning: sqlite3.Connection) -> bool:
    return (
        anslutning.execute(
            "SELECT count(*) FROM sqlite_master"
            " WHERE type = 'table' AND name = 'gpkg_contents'"
        ).fetchone()[0]
        == 1
    )


def _registrera(anslutning: sqlite3.Connection, tabell: str, beskrivning: str) -> None:
    """Gor tabellen synlig som attributlager i QGIS.

    srs_id satts till 0, "Undefined geographic SRS", inte NULL. Specifikationen
    tillater bada for attributlager, men RAA:s eget uttag ar skrivet av GDAL med
    0 pa sina attributtabeller -- och det ar den filen som bevisligen oppnas i
    QGIS har. Att folja den skrivningen ar billigare an att prova sig fram.
    """
    anslutning.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (tabell,))
    anslutning.execute(
        "INSERT INTO gpkg_contents"
        " (table_name, data_type, identifier, description, last_change, srs_id)"
        " VALUES (?, 'attributes', ?, ?, ?, 0)",
        (tabell, tabell, beskrivning, _tidsstampel()),
    )


def skriv_till_gpkg(
    databas: Path | str,
    gpkg: Path | str,
    tolkning: list[Skikt] | None = None,
    lanen: list[str] | None = None,
) -> Exportrapport:
    """Skriver om lamningstypstabellerna i GPKG:n. Idempotent.

    `tolkning` ar uteslutningsskiktet. Det skrivs i egna tabeller och med niva
    och lan per post -- det ska aldrig ga att forvaxla med RAA:s text.

    `lanen` ar de lan uttaget valdes for. Utan dem lases lanet ur datan: det
    vanligaste. Det racker for ett lan men inte for tva -- ett uttag over
    lansgransen skulle da tyst tappa det mindre lanets regionala poster.
    """
    databas, gpkg = Path(databas), Path(gpkg)
    if not gpkg.exists():
        raise FileNotFoundError(f"ingen GPKG pa {gpkg}")

    kalla = sqlite3.connect(databas)
    kalla.row_factory = sqlite3.Row
    mal = sqlite3.connect(gpkg)
    try:
        if not _ar_gpkg(mal):
            raise ValueError(f"{gpkg.name} ar ingen GeoPackage: gpkg_contents saknas")

        stampel = kalla.execute(
            "SELECT listversion, hamtdatum, sha256 FROM kalla WHERE id = 1"
        ).fetchone()
        modell = kalla.execute(
            "SELECT modellversion, byggd FROM modell WHERE id = 1"
        ).fetchone()

        # `visa_stod` ar en installning nagon gjort i filen, inte data ur
        # listan. Exporten bygger om varje tabell fran grunden och skulle
        # annars nolla den vid varje korning -- och sedan anvisningarna bakas
        # in maste exporten koras om for att en andring ska sla igenom, vilket
        # gjort inställningen omojlig att anvanda alls.
        bevarat_stod = _befintligt_visa_stod(mal)

        for tabell in TABELLER + UTGANGNA:
            mal.execute(f'DROP TABLE IF EXISTS "{PREFIX}{tabell}"')
            mal.execute(
                "DELETE FROM gpkg_contents WHERE table_name = ?", (PREFIX + tabell,)
            )

        rader: dict[str, int] = {}
        lansfordelning = _lan_i_uttaget(mal)
        valda = lansmodul.lista(lanen or [])
        if not valda:
            valda = [next(iter(lansfordelning))] if lansfordelning else []
        lan = valda[0] if valda else ""
        # Samma form som RAA:s egen lan-kolumn for en lamning i tva lan.
        rader.update(
            _skriv_modell(mal, stampel, modell, databas.name, ",".join(valda))
        )
        typrader, oidentifierade = _skriv_lamningstyper(mal, kalla, bevarat_stod)
        rader.update(typrader)
        rader.update(_skriv_egenskaper(mal, kalla))
        rader.update(_skriv_relationer(mal, kalla))
        rader.update(_skriv_avgransningar(mal, kalla))
        # Skiktet kommer ur databasen om ingen listar det. Faltdelen gaar
        # alltid den vagen -- den ska inte behova TOML-filerna.
        skikt = tolkning if tolkning is not None else las_ur_databas(kalla)
        rader.update(_skriv_tolkning(mal, skikt, valda))
        rader.update(_skriv_formregler(mal))
        rader.update(_skriv_beskrivningar(mal, kalla))
        rader.update(_skriv_motiveringskrav(mal, kalla))
        # Sist: anvisningarna byggs ur alla tabeller ovan.
        rader.update(_skriv_anvisningar(mal))
        # Alla verktygets egna kolumner, inte bara indicierna. Migreringen
        # lade till hela uppsattningen medan exporten bara lade till en del --
        # och da fick en befintlig uppsattning aldrig de nya faltena.
        tillagda = faltmodul.sakerstall_kolumner(
            mal, _registertabeller(mal), faltmodul.ALLA_EGNA
        )
        i_bruk = mal.execute(
            f'SELECT count(*) FROM "{PREFIX}lamningstyp" WHERE forekomst > 0'
        ).fetchone()[0]
        mal.commit()
    finally:
        kalla.close()
        mal.close()

    return Exportrapport(
        gpkg=gpkg,
        listversion=stampel["listversion"],
        hamtdatum=stampel["hamtdatum"],
        modellversion=modell["modellversion"],
        rader=rader,
        tillagda_kolumner=tillagda,
        lan=lan,
        lanen=valda,
        lansfordelning=lansfordelning,
        typer_i_bruk=i_bruk,
        oidentifierade=oidentifierade,
    )


def _befintligt_visa_stod(mal: sqlite3.Connection) -> dict[str, int]:
    """Vilka lamningstyper nagon tystat i den har arbetsfilen."""
    try:
        return {
            rad[0]: rad[1]
            for rad in mal.execute(
                f'SELECT benamning, visa_stod FROM "{PREFIX}lamningstyp"'
            ).fetchall()
            if rad[1] == 0
        }
    except sqlite3.OperationalError:
        return {}


def _skriv_modell(
    mal: sqlite3.Connection,
    stampel: sqlite3.Row,
    modell: sqlite3.Row,
    kallfil: str,
    lan: str,
) -> dict[str, int]:
    mal.execute(
        f'CREATE TABLE "{PREFIX}modell" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " listversion TEXT NOT NULL,"
        " hamtdatum TEXT NOT NULL,"
        " modellversion TEXT NOT NULL,"
        " sha256 TEXT NOT NULL,"
        " byggd TEXT NOT NULL,"
        " kallfil TEXT NOT NULL,"
        # Vilket lan uttaget tacker. Last ur datan, inte ur filnamnet:
        # filnamn byts, innehall gor det inte.
        " lan TEXT NOT NULL DEFAULT '',"
        " inskriven TEXT NOT NULL)"
    )
    mal.execute(
        f'INSERT INTO "{PREFIX}modell"'
        " (listversion, hamtdatum, modellversion, sha256, byggd, kallfil, lan,"
        " inskriven) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            stampel["listversion"],
            stampel["hamtdatum"],
            modell["modellversion"],
            stampel["sha256"],
            modell["byggd"],
            kallfil,
            lan,
            _tidsstampel(),
        ),
    )
    _registrera(
        mal,
        PREFIX + "modell",
        f"Lämningstypslistan {stampel['listversion']}, hämtad "
        f"{stampel['hamtdatum']}, modellversion {modell['modellversion']}",
    )
    return {"modell": 1}


def _registertabeller(mal: sqlite3.Connection) -> list[str]:
    """RAA:s egna lager i uttaget som bar en lamningstyp."""
    # Bara riktiga tabeller. gpkg_contents listar aven vyer -- uttaget har
    # flera som joinar lamning mot geometritabellerna, och de skulle dels
    # dubbelrakna, dels falla pa en tvetydig kolumn i sin egen SQL.
    #
    # Hela listan hamtas hem forst: en ny execute pa samma anslutning stanger
    # markoren for den yttre fragan.
    #
    # Geometritabellerna forst. RAA:s centrala `lamning` bar samma lamningstyp
    # en gaang till, och rakna bada ger dubbelt.
    def med_kolumn(sort: str) -> list[str]:
        namn = [
            rad[0]
            for rad in mal.execute(
                "SELECT c.table_name FROM gpkg_contents c"
                " JOIN sqlite_master m ON m.name = c.table_name AND m.type = 'table'"
                " WHERE c.data_type = ? AND c.table_name NOT LIKE ?",
                (sort, PREFIX + "%"),
            ).fetchall()
        ]
        traffar = []
        for tabell in namn:
            kolumner = {
                k[1] for k in mal.execute(f'PRAGMA table_info("{tabell}")').fetchall()
            }
            if "lamningstyp" in kolumner:
                traffar.append(tabell)
        return traffar

    tabeller = med_kolumn("features")
    if tabeller:
        return tabeller

    # Ett raa uttag har inga attribut i geometritabellerna -- `point` bar bara
    # fid, geometri, lamning_uuid och geometrinummer. Allt annat ligger i
    # `lamning`, och forst migreringen kopierar over det. Exporten ska duga
    # aven da, alltsa direkt efter nedladdning.
    return med_kolumn("attributes")


def _lan_i_uttaget(mal: sqlite3.Connection) -> dict[str, int]:
    """Vilka lan uttaget tacker, raknat ur datan sjalv.

    En lamning kan ligga i tva lan -- kolumnen bar da bada, kommaseparerat.
    Grannlanen syns darfor med sma tal, och det ar rimligt: det ar samma
    lamning, inte ett fel i uttaget.
    """
    fordelning: dict[str, int] = {}
    for tabell in _registertabeller(mal):
        kolumner = {
            rad[1] for rad in mal.execute(f'PRAGMA table_info("{tabell}")').fetchall()
        }
        if "lan" not in kolumner:
            continue
        for varde, antal in mal.execute(
            f'SELECT lan, count(*) FROM "{tabell}" WHERE lan IS NOT NULL GROUP BY 1'
        ).fetchall():
            for namn in str(varde).split(","):
                nyckel = lansmodul.normalisera(namn)
                if nyckel:
                    fordelning[nyckel] = fordelning.get(nyckel, 0) + antal
    return dict(sorted(fordelning.items(), key=lambda post: -post[1]))


def _forekomster(mal: sqlite3.Connection) -> dict[str, int]:
    """Hur manga lamningar av varje typ som star i just det har lansuttaget.

    Rakningen gaar over normaliserad benamning: registret och listan stavar
    inte lika, och utan det tappas de 41 jamtlandska lamningarna under
    "Grav - uppgift om typ saknas" tyst.
    """
    # En lamning kan ha bade punkt och yta. Rakningen gaar over lamningens
    # egen identitet dar den finns, sa att samma lamning raknas en gaang.
    per_typ: dict[str, set[str]] = {}
    raknade: dict[str, int] = {}
    for tabell in _registertabeller(mal):
        kolumner = {
            rad[1] for rad in mal.execute(f'PRAGMA table_info("{tabell}")').fetchall()
        }
        if "lamning_uuid" in kolumner:
            for typ, identitet in mal.execute(
                f'SELECT lamningstyp, lamning_uuid FROM "{tabell}"'
                " WHERE lamningstyp IS NOT NULL"
            ).fetchall():
                per_typ.setdefault(normalisera(typ), set()).add(identitet)
        else:
            for typ, antal in mal.execute(
                f'SELECT lamningstyp, count(*) FROM "{tabell}"'
                " WHERE lamningstyp IS NOT NULL GROUP BY 1"
            ).fetchall():
                nyckel = normalisera(typ)
                raknade[nyckel] = raknade.get(nyckel, 0) + antal

    for nyckel, identiteter in per_typ.items():
        raknade[nyckel] = raknade.get(nyckel, 0) + len(identiteter)
    return raknade


def _geometrifordelning(mal: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Hur manga lamningar av varje typ som ar punkt, linje respektive yta.

    Fornreg binder geometrin till lamningens storlek och inte till dess typ:
    under 20 m punkt, over 20 m yta, strangar och halvagar linje -- och nara
    en fastighetsgrans yta oavsett storlek. Nagon regel "den har typen far
    aldrig vara en yta" finns alltsa inte att hamta.

    Det som daremot finns ar registrets egen praxis. Ar 6 849 av 7 072
    bekraftade fangstgropar punkter sager det nagot om de 23 ovriga.

    Tva forbehall, bada verkliga:

    Obekraftade uppgifter raknas inte. En uppgift om en fangstgrop ritas som
    en yta over det omrade dar den kan tankas ligga -- 22 av de 46
    fangstgropsytorna ar sadana, och de sager ingenting om hur en fangstgrop
    bor geometrisattas. Se `EJ_EGEN_UTBREDNING`.

    Och praxis ar inte detsamma som riktighet. Aldre registreringar bar egna
    fel, sa underlaget innehaller en del av det som ska hittas. Talen skrivs
    darfor ut i sin helhet: anmarkningen pekar, den domer inte, och den som
    laser ser vad pastaendet vilar pa.
    """
    fordelning: dict[str, dict[str, int]] = {}
    for tabell in ("point", "linestring", "polygon"):
        if not mal.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = ?",
            (tabell,),
        ).fetchone()[0]:
            continue
        kolumner = {
            rad[1] for rad in mal.execute(f'PRAGMA table_info("{tabell}")').fetchall()
        }
        if "lamningstyp" not in kolumner:
            continue
        villkor = ""
        if "aktualitetstatus" in kolumner:
            platshallare = ", ".join("?" for _ in EJ_EGEN_UTBREDNING)
            villkor = (
                f" AND (aktualitetstatus IS NULL"
                f" OR aktualitetstatus NOT IN ({platshallare}))"
            )
        for typ, antal in mal.execute(
            f'SELECT lamningstyp, count(*) FROM "{tabell}"'
            f" WHERE lamningstyp IS NOT NULL{villkor} GROUP BY 1",
            EJ_EGEN_UTBREDNING if villkor else (),
        ).fetchall():
            fordelning.setdefault(normalisera(typ), {})[tabell] = antal
    return fordelning


def _skriv_lamningstyper(
    mal: sqlite3.Connection,
    kalla: sqlite3.Connection,
    bevarat_stod: dict[str, int] | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    mal.execute(
        f'CREATE TABLE "{PREFIX}lamningstyp" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " benamning TEXT NOT NULL UNIQUE,"
        " sida INTEGER NOT NULL,"
        " definition TEXT NOT NULL,"
        " kommentar TEXT NOT NULL,"
        " bedomning TEXT NOT NULL,"
        " sammansatt INTEGER NOT NULL,"
        " ordning INTEGER NOT NULL,"
        # Handboken: stodet ska ga att stanga av per lamningstyp. Van
        # inventerare behover ingen paminnelse om mattordningen;
        # forstaarsinventeraren gor det. Satt 0 for att tysta anvisningarna
        # for en typ -- en rad att andra, inte ett granssnitt att skriva om.
        " visa_stod INTEGER NOT NULL DEFAULT 1,"
        # Hur typen ar geometrisatt i det har uttaget. Inte en regel -- Fornreg
        # binder geometrin till lamningens storlek, inte till dess typ -- utan
        # registrets egen praxis, raknad ur datan. En fangstgrop som yta ar
        # inte forbjuden, men den ar en av 46 mot 7 209 punkter, och det ar
        # vart att titta pa.
        " antal_punkt INTEGER NOT NULL DEFAULT 0,"
        " antal_linje INTEGER NOT NULL DEFAULT 0,"
        " antal_yta INTEGER NOT NULL DEFAULT 0,"
        # Antal registrerade lamningar av typen i just det har lansuttaget.
        # Gor det mojligt att filtrera rullistan till det som forekommer
        # regionalt -- utan att, som den gamla ValueMap-listan, gora de
        # ovriga omojliga att valja.
        " forekomst INTEGER NOT NULL DEFAULT 0)"
    )
    poster = kalla.execute(
        "SELECT benamning, sida, definition, kommentar, bedomning, sammansatt,"
        " ordning FROM lamningstyp ORDER BY ordning"
    ).fetchall()
    raknade = _forekomster(mal)
    per_geometri = _geometrifordelning(mal)

    # Raderna skrivs i den ordning rullistan ska visa dem: vanligast i det
    # har lanet forst.
    #
    # Listan har 157 typer och de flesta av dem forekommer inte alls i ett
    # givet lan. Alfabetisk ordning lagger Avrattningsplats och Ballastplats
    # overst och Stensattning -- 4 000 i Jamtland -- en bra bit ned, sa man
    # rullar forbi det troliga for att komma till det ovanliga.
    #
    # Ordningen har styr attributtabellen, inte formularets rullista. Den
    # ligger i projektet, en egen per geometrisort -- se
    # faltdel/formular.satt_typlista. Att sortera raderna anda ar billigt och
    # gor tabellen lika lattlast som listan.
    #
    # Typer som saknas i lanet ligger sist i bokstavsordning. De gaar
    # fortfarande att valja -- ett lan far sin forsta lamning av en typ nan
    # gang, och det ska inte vara omojligt att registrera.
    def vanlighet(rad):
        namn = normalisera(rad["benamning"])
        return (-raknade.get(namn, 0), rad["benamning"])

    poster = sorted(poster, key=vanlighet)

    mal.executemany(
        f'INSERT INTO "{PREFIX}lamningstyp"'
        " (benamning, sida, definition, kommentar, bedomning, sammansatt, ordning,"
        " forekomst, antal_punkt, antal_linje, antal_yta)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            tuple(rad)
            + (raknade.get(normalisera(rad["benamning"]), 0),)
            + tuple(
                per_geometri.get(normalisera(rad["benamning"]), {}).get(sort, 0)
                for sort in ("point", "linestring", "polygon")
            )
            for rad in poster
        ],
    )
    # Installningen aterstalls efter ombygget. Den ar nagot en manniska gjort
    # i den har filen, inte data ur listan, och exporten far inte nolla den.
    for benamning in bevarat_stod or {}:
        mal.execute(
            f'UPDATE "{PREFIX}lamningstyp" SET visa_stod = 0 WHERE benamning = ?',
            (benamning,),
        )

    kanda = {normalisera(rad["benamning"]) for rad in poster}
    oidentifierade = {
        typ: antal for typ, antal in raknade.items() if typ not in kanda
    }
    _registrera(
        mal,
        PREFIX + "lamningstyp",
        "Lämningstyper med definition, kommentar och antikvarisk bedömning, "
        "ordagrant ur listan",
    )

    mal.execute(
        f'CREATE TABLE "{PREFIX}kategori" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " benamning TEXT NOT NULL,"
        " kategori TEXT NOT NULL)"
    )
    kategorier = kalla.execute(
        "SELECT benamning, kategori FROM kategori ORDER BY benamning, kategori"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}kategori" (benamning, kategori) VALUES (?, ?)',
        [tuple(rad) for rad in kategorier],
    )
    _registrera(mal, PREFIX + "kategori", "Kategoritillhörighet enligt listans bilaga")
    return (
        {"lamningstyp": len(poster), "kategori": len(kategorier)},
        oidentifierade,
    )


def _skriv_egenskaper(
    mal: sqlite3.Connection, kalla: sqlite3.Connection
) -> dict[str, int]:
    mal.execute(
        f'CREATE TABLE "{PREFIX}egenskapstyp" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " benamning TEXT NOT NULL,"
        " typnamn TEXT NOT NULL,"
        " flervard INTEGER NOT NULL,"
        " ordning INTEGER NOT NULL)"
    )
    typer = kalla.execute(
        "SELECT benamning, typnamn, flervard, ordning FROM egenskapstyp"
        " ORDER BY benamning, ordning"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}egenskapstyp"'
        " (benamning, typnamn, flervard, ordning) VALUES (?, ?, ?, ?)",
        [tuple(rad) for rad in typer],
    )
    _registrera(
        mal, PREFIX + "egenskapstyp", "Egenskapstyper per lämningstyp"
    )

    # Denormaliserad med flit: QGIS filteruttryck kan inte joina, och
    # egenskapsvardena ska filtreras pa vald lamningstyp i formularet.
    mal.execute(
        f'CREATE TABLE "{PREFIX}egenskapsvarde" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " benamning TEXT NOT NULL,"
        " typnamn TEXT NOT NULL,"
        " varde TEXT NOT NULL,"
        " ordning INTEGER NOT NULL)"
    )
    varden = kalla.execute(
        "SELECT e.benamning, e.typnamn, v.varde, v.ordning"
        " FROM egenskapsvarde v JOIN egenskapstyp e ON e.id = v.egenskapstyp"
        " ORDER BY e.benamning, e.ordning, v.ordning"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}egenskapsvarde"'
        " (benamning, typnamn, varde, ordning) VALUES (?, ?, ?, ?)",
        [tuple(rad) for rad in varden],
    )
    mal.execute(
        f'CREATE INDEX "ix_{PREFIX}egenskapsvarde"'
        f' ON "{PREFIX}egenskapsvarde" (benamning, typnamn)'
    )
    _registrera(
        mal,
        PREFIX + "egenskapsvarde",
        "Egenskapsvärden, filtrerbara på lämningstyp och egenskapstyp",
    )
    return {"egenskapstyp": len(typer), "egenskapsvarde": len(varden)}


def _skriv_relationer(
    mal: sqlite3.Connection, kalla: sqlite3.Connection
) -> dict[str, int]:
    mal.execute(
        f'CREATE TABLE "{PREFIX}ingaende_typ" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sammansatt TEXT NOT NULL,"
        " ingaende TEXT NOT NULL)"
    )
    ingaende = kalla.execute(
        "SELECT sammansatt, ingaende FROM ingaende_typ ORDER BY sammansatt, ingaende"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}ingaende_typ" (sammansatt, ingaende) VALUES (?, ?)',
        [tuple(rad) for rad in ingaende],
    )
    _registrera(
        mal, PREFIX + "ingaende_typ", "Sammansatta lämningstyper och deras delar"
    )

    # Jfr-lankarna ar uteslutningsgrafens grundstomme. I falt ar det de som
    # bar kontextvarningen: vad ska uteslutas innan typvalet star fast.
    mal.execute(
        f'CREATE TABLE "{PREFIX}jfr" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " fran TEXT NOT NULL,"
        " till TEXT NOT NULL)"
    )
    lankar = kalla.execute("SELECT fran, till FROM jfr ORDER BY fran, till").fetchall()
    # Bada riktningarna skrivs: forvaxlingsrisken ar omsesidig aven nar
    # listan bara satte sitt Jfr i den ena anden.
    par = {(rad["fran"], rad["till"]) for rad in lankar}
    par |= {(till, fran) for fran, till in par}
    mal.executemany(
        f'INSERT INTO "{PREFIX}jfr" (fran, till) VALUES (?, ?)', sorted(par)
    )
    mal.execute(f'CREATE INDEX "ix_{PREFIX}jfr" ON "{PREFIX}jfr" (fran)')
    _registrera(
        mal,
        PREFIX + "jfr",
        "Listans Jfr-hänvisningar, åt båda hållen — vad som ska uteslutas",
    )
    return {"ingaende_typ": len(ingaende), "jfr": len(par)}


def _skriv_avgransningar(
    mal: sqlite3.Connection, kalla: sqlite3.Connection
) -> dict[str, int]:
    """Listans egna "Avser inte"-satser.

    Det har ar RAA:s normerande text om vad en typ inte omfattar -- "Avser
    inte kavelbroar, dessa aterfinns under Fardvag" -- och den hor till
    typbestamningen. Den lag i lager 1 fran borjan men exporterades aldrig,
    sa tretton satser stannade i databasen.

    Den visas i samma falt som uteslutningarna men markt med sin harkomst.
    Skillnaden far inte suddas: listans ord ar foreskrift, tolkningsskiktet ar
    regional erfarenhet.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}avgransning" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL,"
        " sats TEXT NOT NULL)"
    )
    poster = kalla.execute(
        "SELECT benamning, sats FROM avgransning ORDER BY benamning"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}avgransning" (lamningstyp, sats) VALUES (?, ?)',
        [tuple(rad) for rad in poster],
    )
    mal.execute(
        f'CREATE INDEX "ix_{PREFIX}avgransning"'
        f' ON "{PREFIX}avgransning" (lamningstyp)'
    )
    _registrera(
        mal,
        PREFIX + "avgransning",
        "Listans egna ”Avser inte”-satser — vad lämningstypen inte omfattar",
    )
    return {"avgransning": len(poster)}


def _skriv_anvisningar(mal: sqlite3.Connection) -> dict[str, int]:
    """En rad per lamningstyp med fardig text for varje falt i formularet.

    Falten hamtade sin text med `aggregate()`, som gor en filtrerad
    genomsokning av uppslagslagret per rad. I formularet ar det fyra anrop for
    en lamning och marks inte. I attributtabellen ar det sex anrop gaanger
    25 820 rader -- QGIS slutade svara och maste tvangsstangas.

    Texten byggs darfor har, en gaang, och slaas upp med `get_feature` mot ett
    unikt index: ett uppslag per falt i stallet for en genomsokning.

    Ordningen bestams ocksa har, dar den gaar att lasa. Falthandbokens undantag
    star fore Exempelsamlingens princip -- den som slaar upp Kolningsanlaggning
    behover veta att kolbottnens egna matt galler innan hon laser den allmanna
    regeln, inte efter.

    `visa_stod` bakas in: satts den till 0 skrivs tomma stranger och
    anvisningarna tystnar. Andringen kraver att exporten kors om, vilket ar
    priset for att attributtabellen ska ga att oppna.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}anvisning" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL UNIQUE,"
        " uteslut TEXT NOT NULL DEFAULT '',"
        " mattregel TEXT NOT NULL DEFAULT '',"
        " exempel TEXT NOT NULL DEFAULT '',"
        " motivering TEXT NOT NULL DEFAULT '')"
    )

    def samla(fraga: str) -> dict[str, list[str]]:
        ut: dict[str, list[str]] = {}
        for typ, text in mal.execute(fraga).fetchall():
            if text:
                ut.setdefault(typ, []).append(text)
        return ut

    # Listans egna "Avser inte"-satser forst, markta, sedan tolkningsskiktet.
    avgransning = samla(
        f'SELECT lamningstyp, sats FROM "{PREFIX}avgransning" ORDER BY fid'
    )
    uteslutning = samla(
        f'SELECT lamningstyp, kontextvarning FROM "{PREFIX}uteslutning"'
        " ORDER BY fid"
    )
    tillagg = samla(
        f'SELECT lamningstyp, text FROM "{PREFIX}beskrivningstillagg"'
        " ORDER BY fid"
    )
    princip = samla(
        f'SELECT lamningstyp, text FROM "{PREFIX}beskrivningsprincip"'
    )
    exempel = samla(
        "SELECT lamningstyp, CASE WHEN nyckel = ''"
        " THEN text ELSE nyckel || ' — ' || text END"
        f' FROM "{PREFIX}beskrivningsexempel" ORDER BY ordning'
    )
    besked = dict(
        mal.execute(
            f'SELECT lamningstyp, besked FROM "{PREFIX}motivering"'
        ).fetchall()
    )

    rad = chr(10)
    stycke = chr(10) * 2
    rader = []
    for typ, visa in mal.execute(
        f'SELECT benamning, visa_stod FROM "{PREFIX}lamningstyp" ORDER BY ordning'
    ).fetchall():
        # Motiveringen ar ett krav i KRFS 2022:3 och tystas aldrig.
        motivering = besked.get(typ, "")
        if not visa:
            rader.append((typ, "", "", "", motivering))
            continue
        uteslut = [f"Listan: {sats}" for sats in avgransning.get(typ, [])]
        uteslut += uteslutning.get(typ, [])
        matt = [f"Fälthandboken: {text}" for text in tillagg.get(typ, [])]
        matt += princip.get(typ, [])
        rader.append(
            (
                typ,
                rad.join(uteslut),
                stycke.join(matt),
                stycke.join(exempel.get(typ, [])),
                motivering,
            )
        )

    mal.executemany(
        f'INSERT INTO "{PREFIX}anvisning"'
        " (lamningstyp, uteslut, mattregel, exempel, motivering)"
        " VALUES (?, ?, ?, ?, ?)",
        rader,
    )
    _registrera(
        mal,
        PREFIX + "anvisning",
        "Färdig anvisningstext per lämningstyp — det formulärets fält slår upp",
    )
    return {"anvisning": len(rader)}


def _skriv_tolkning(
    mal: sqlite3.Connection, skikt: list[Skikt], lanen: list[str]
) -> dict[str, int]:
    """Uteslutningsskiktet, med niva och lan per post.

    Nationella poster foljer alltid med. Regionala tas bara med for de lan
    uttaget tacker -- en jamtlandsk erfarenhet hor inte hemma i ett skanskt
    faltformular, och att den syns dar vore varre an att den saknas. Gaar
    arbetet over lansgransen hor bada lanens poster hemma, var och en med
    sitt lan utskrivet.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}uteslutning" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL,"
        " egenskapstyp TEXT NOT NULL DEFAULT '',"
        " egenskapsvarde TEXT NOT NULL DEFAULT '',"
        " uteslut TEXT NOT NULL DEFAULT '',"
        " fragor TEXT NOT NULL DEFAULT '',"
        " sarskiljande TEXT NOT NULL DEFAULT '',"
        " kontextvarning TEXT NOT NULL,"
        " niva TEXT NOT NULL,"
        " lan TEXT NOT NULL DEFAULT '')"
    )
    mal.execute(
        f'CREATE TABLE "{PREFIX}beskrivningstillagg" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL,"
        " egenskapstyp TEXT NOT NULL DEFAULT '',"
        " egenskapsvarde TEXT NOT NULL DEFAULT '',"
        " text TEXT NOT NULL,"
        " niva TEXT NOT NULL,"
        " lan TEXT NOT NULL DEFAULT '')"
    )
    uteslutningar = 0
    tillagg = 0
    for ett_skikt in skikt:
        if ett_skikt.lan and lanen and ett_skikt.lan not in lanen:
            continue
        for post in ett_skikt.uteslutningar:
            mal.execute(
                f'INSERT INTO "{PREFIX}uteslutning"'
                " (lamningstyp, egenskapstyp, egenskapsvarde, uteslut, fragor,"
                " sarskiljande, kontextvarning, niva, lan)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    post.lamningstyp,
                    post.egenskapstyp,
                    post.egenskapsvarde,
                    " · ".join(post.uteslut),
                    " ".join(post.fragor),
                    post.sarskiljande,
                    post.som_kontextvarning(),
                    post.niva,
                    post.lan,
                ),
            )
            uteslutningar += 1
        for post in ett_skikt.beskrivningstillagg:
            mal.execute(
                f'INSERT INTO "{PREFIX}beskrivningstillagg"'
                " (lamningstyp, egenskapstyp, egenskapsvarde, text, niva, lan)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    post.lamningstyp,
                    post.egenskapstyp,
                    post.egenskapsvarde,
                    post.text,
                    post.niva,
                    post.lan,
                ),
            )
            tillagg += 1

    mal.execute(
        f'CREATE INDEX "ix_{PREFIX}uteslutning"'
        f' ON "{PREFIX}uteslutning" (lamningstyp)'
    )
    _registrera(
        mal,
        PREFIX + "uteslutning",
        "Vad som ska uteslutas innan typvalet står fast — regional erfarenhet, "
        "inte RAÄ:s normerande text",
    )
    mal.execute(
        f'CREATE INDEX "ix_{PREFIX}beskrivningstillagg"'
        f' ON "{PREFIX}beskrivningstillagg" (lamningstyp)'
    )
    _registrera(
        mal,
        PREFIX + "beskrivningstillagg",
        "Fälthandbokens förtydliganden till beskrivningsprincipen — "
        "regional erfarenhet, inte RAÄ:s normerande text",
    )
    return {
        "uteslutning": uteslutningar,
        "beskrivningstillagg": tillagg,
    }


def _skriv_formregler(mal: sqlite3.Connection) -> dict[str, int]:
    """Falthandbokens allmanna formregler for matt.

    Fem rader, inte 157. Reglerna galler varje lamningstyp -- decimaler,
    ordning, varifran djup mats -- och skrivs darfor en gaang. Den forra
    versionen hade en rad per typ, harledd ur typens namn, och sammanfogade
    dem i formularet till motstridiga anvisningar. Det som faktiskt ar
    typspecifikt ligger nu i ark_beskrivningsprincip.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}formregel" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " rubrik TEXT NOT NULL,"
        " text TEXT NOT NULL,"
        " ordning INTEGER NOT NULL,"
        " niva TEXT NOT NULL,"
        " kalla TEXT NOT NULL)"
    )
    poster = mattregelmodul.formregler()
    mal.executemany(
        f'INSERT INTO "{PREFIX}formregel"'
        " (rubrik, text, ordning, niva, kalla) VALUES (?, ?, ?, ?, ?)",
        [
            (post.rubrik, post.text, ordning, post.niva, post.kalla)
            for ordning, post in enumerate(poster)
        ],
    )
    _registrera(
        mal,
        PREFIX + "formregel",
        "Fälthandbokens allmänna formregler för mått — gäller alla lämningstyper",
    )
    return {"formregel": len(poster)}


def _skriv_beskrivningar(
    mal: sqlite3.Connection, kalla: sqlite3.Connection
) -> dict[str, int]:
    """Exempelsamlingens principer och exempel.

    Principen ar en per lamningstyp. Exemplen ar nycklade pa egenskapsvarde,
    och nyckelkolumnerna ar denormaliserade av samma skal som
    ark_egenskapsvarde: QGIS filteruttryck kan inte joina, och exemplet ska
    kunna filtreras pa de varden inventeraren just valt.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}beskrivningsprincip" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL UNIQUE,"
        " text TEXT NOT NULL,"
        " kalla TEXT NOT NULL)"
    )
    principer = kalla.execute(
        "SELECT benamning, text, kalla FROM beskrivningsprincip ORDER BY benamning"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}beskrivningsprincip" (lamningstyp, text, kalla)'
        " VALUES (?, ?, ?)",
        [tuple(rad) for rad in principer],
    )
    _registrera(
        mal,
        PREFIX + "beskrivningsprincip",
        "Hur lämningstypen ska beskrivas, ordagrant ur Exempelsamlingen",
    )

    mal.execute(
        f'CREATE TABLE "{PREFIX}beskrivningsexempel" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL,"
        " text TEXT NOT NULL,"
        " nyckel TEXT NOT NULL DEFAULT '',"
        " egenskapstyp_1 TEXT NOT NULL DEFAULT '',"
        " egenskapsvarde_1 TEXT NOT NULL DEFAULT '',"
        " egenskapstyp_2 TEXT NOT NULL DEFAULT '',"
        " egenskapsvarde_2 TEXT NOT NULL DEFAULT '',"
        " antal TEXT NOT NULL DEFAULT '',"
        " registreras_som TEXT NOT NULL DEFAULT '',"
        " ordning INTEGER NOT NULL,"
        " kalla TEXT NOT NULL)"
    )
    exempel = kalla.execute(
        "SELECT benamning, text, nyckel, egenskapstyp_1, egenskapsvarde_1,"
        " egenskapstyp_2, egenskapsvarde_2, antal, registreras_som, ordning, kalla"
        " FROM beskrivningsexempel ORDER BY ordning"
    ).fetchall()
    mal.executemany(
        f'INSERT INTO "{PREFIX}beskrivningsexempel"'
        " (lamningstyp, text, nyckel, egenskapstyp_1, egenskapsvarde_1,"
        "  egenskapstyp_2, egenskapsvarde_2, antal, registreras_som, ordning,"
        "  kalla) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(rad) for rad in exempel],
    )
    mal.execute(
        f'CREATE INDEX "ix_{PREFIX}beskrivningsexempel"'
        f' ON "{PREFIX}beskrivningsexempel" (lamningstyp)'
    )
    _registrera(
        mal,
        PREFIX + "beskrivningsexempel",
        "Färdiga beskrivningar ur Exempelsamlingen, nycklade på egenskapsvärde",
    )
    return {
        "beskrivningsprincip": len(principer),
        "beskrivningsexempel": len(exempel),
    }


def _skriv_motiveringskrav(
    mal: sqlite3.Connection, kalla: sqlite3.Connection
) -> dict[str, int]:
    """Nar 1850 avgor, och maste motiveras.

    Grunden skrivs med: kravet ska gaa att folja tillbaka till listans egna
    ord, inte behova tros pa.
    """
    mal.execute(
        f'CREATE TABLE "{PREFIX}motivering" ('
        " fid INTEGER PRIMARY KEY AUTOINCREMENT,"
        " lamningstyp TEXT NOT NULL UNIQUE,"
        " kravs INTEGER NOT NULL CHECK (kravs IN (0, 1)),"
        " klass TEXT NOT NULL,"
        # Vad formularet visar. "Ingen motivering behovs" och "listan sager
        # att typen alltid ar fornlamning" ar tva olika besked, och det ar
        # det andra som hjalper i falt.
        " besked TEXT NOT NULL,"
        " grund TEXT NOT NULL,"
        " kalla TEXT NOT NULL)"
    )

    poster = [
        (rad["benamning"], rad["bedomning"])
        for rad in kalla.execute(
            "SELECT benamning, bedomning FROM lamningstyp ORDER BY ordning"
        ).fetchall()
    ]
    ingaende: dict[str, list[str]] = {}
    for sammansatt, del_ in kalla.execute(
        "SELECT sammansatt, ingaende FROM ingaende_typ"
    ).fetchall():
        ingaende.setdefault(sammansatt, []).append(del_)

    krav = motiveringsmodul.krav(poster, ingaende)
    mal.executemany(
        f'INSERT INTO "{PREFIX}motivering"'
        " (lamningstyp, kravs, klass, besked, grund, kalla)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                post.lamningstyp,
                int(post.kravs),
                post.klass,
                post.besked,
                post.grund,
                motiveringsmodul.KALLA,
            )
            for post in krav
        ],
    )
    _registrera(
        mal,
        PREFIX + "motivering",
        "När antagandet om tillkomsttid måste motiveras enligt KRFS 2022:3",
    )
    return {"motivering": len(krav)}
