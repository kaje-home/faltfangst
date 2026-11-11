"""Laesbara uppslagstabeller i QGIS.

Uppslagslagren skrevs till varje uttag utan en enda instaellning: inga alias,
inga dolda hjaelpkolumner, inga flerradiga textfaelt. En attributtabell aer ett
rutnaet, och `ark_anvisning.exempel` aer 1 209 tecken. Pa en tiotumsskaerm blir
det en rad man inte kan laesa.

Det som goer skillnaden aer inte tabellvyn utan **formulaervyn** -- knappen nere
till hoeger i attributtabellen. Den visar en post i taget med etiketter och
radbruten text, och den finns redan i QGIS. Den hade bara ingenting att visa
upp: utan alias staar kolumnnamnen som de heter i basen, och utan IsMultiline
klipps en 1 200 tecken lang text till en enradig ruta.

Tre saker skrivs in per lager:

* **alias** -- svensk etikett, syns bade som kolumnrubrik och som faeltnamn i
  formulaervyn
* **attributetableconfig** -- vilka kolumner som doeljs, och hur bred varje
  kolumn aer
* **fieldConfiguration** -- IsMultiline pa de langa texterna

Dolda kolumner aer alltid samma sort: `fid`, `ordning` och de raknade
kolumnerna som styr geometripraxis. De behoevs av verktyget och saeger
inventeraren ingenting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.sax.saxutils import escape

# Bredd i punkter for en lang textkolumn i tabellvyn. -1 betyder automatisk,
# vilket for en 1 200 tecken lang text blir en kolumn utan slut.
_LANGBREDD = 420


@dataclass(frozen=True)
class Kolumn:
    """En kolumn i ett uppslagslager."""

    namn: str
    etikett: str
    dold: bool = False
    lang: bool = False


@dataclass(frozen=True)
class Tabellvy:
    """Hur ett uppslagslager ska visas."""

    lager: str
    sortera: str
    kolumner: tuple[Kolumn, ...]


def _dold(namn: str) -> Kolumn:
    return Kolumn(namn, "", dold=True)


# Ordningen aer den som kolumnerna star i basen. Etiketterna aer formularets
# egna dar de finns -- "Uteslut", "Matt", "Listan saeger" -- sa att den som
# slar upp tabellen kaenner igen sig fran blanketten.
UPPSLAGSVYER: tuple[Tabellvy, ...] = (
    Tabellvy(
        "ark_anvisning",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("uteslut", "Uteslut", lang=True),
            Kolumn("mattregel", "Mått", lang=True),
            Kolumn("exempel", "Exempel på beskrivning", lang=True),
            Kolumn("motivering", "Listan säger", lang=True),
        ),
    ),
    Tabellvy(
        "ark_lamningstyp",
        "benamning",
        (
            _dold("fid"),
            Kolumn("benamning", "Lämningstyp"),
            Kolumn("sida", "Sida i listan"),
            Kolumn("definition", "Definition", lang=True),
            Kolumn("kommentar", "Kommentar", lang=True),
            Kolumn("bedomning", "Antikvarisk bedömning", lang=True),
            Kolumn("sammansatt", "Sammansatt typ"),
            _dold("ordning"),
            Kolumn("visa_stod", "Visa stöd i fält"),
            _dold("antal_punkt"),
            _dold("antal_linje"),
            _dold("antal_yta"),
            Kolumn("forekomst", "Finns i länet"),
        ),
    ),
    Tabellvy(
        "ark_beskrivningsprincip",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("text", "Beskrivningsprincip", lang=True),
            Kolumn("kalla", "Källa"),
        ),
    ),
    Tabellvy(
        "ark_beskrivningsexempel",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("text", "Exempel", lang=True),
            Kolumn("nyckel", "Gäller"),
            _dold("egenskapstyp_1"),
            _dold("egenskapsvarde_1"),
            _dold("egenskapstyp_2"),
            _dold("egenskapsvarde_2"),
            Kolumn("antal", "Antal"),
            Kolumn("registreras_som", "Registreras som"),
            _dold("ordning"),
            Kolumn("kalla", "Källa"),
        ),
    ),
    Tabellvy(
        "ark_beskrivningstillagg",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("egenskapstyp", "Egenskap"),
            Kolumn("egenskapsvarde", "Värde"),
            Kolumn("text", "Tillägg", lang=True),
            Kolumn("niva", "Nivå"),
            Kolumn("lan", "Län"),
        ),
    ),
    Tabellvy(
        "ark_uteslutning",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("egenskapstyp", "Egenskap"),
            Kolumn("egenskapsvarde", "Värde"),
            Kolumn("uteslut", "Kan förväxlas med", lang=True),
            Kolumn("fragor", "Frågor att ställa", lang=True),
            Kolumn("sarskiljande", "Särskiljande drag", lang=True),
            Kolumn("kontextvarning", "Som det visas i fält", lang=True),
            Kolumn("niva", "Nivå"),
            Kolumn("lan", "Län"),
        ),
    ),
    Tabellvy(
        "ark_avgransning",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("sats", "Avser inte", lang=True),
        ),
    ),
    Tabellvy(
        "ark_motivering",
        "lamningstyp",
        (
            _dold("fid"),
            Kolumn("lamningstyp", "Lämningstyp"),
            Kolumn("kravs", "Motivering krävs"),
            Kolumn("klass", "Klass"),
            Kolumn("besked", "Listan säger", lang=True),
            Kolumn("grund", "Grund i listans text", lang=True),
            Kolumn("kalla", "Källa"),
        ),
    ),
    Tabellvy(
        "ark_formregel",
        "ordning",
        (
            _dold("fid"),
            Kolumn("rubrik", "Rubrik"),
            Kolumn("text", "Regel", lang=True),
            _dold("ordning"),
            Kolumn("niva", "Nivå"),
            Kolumn("kalla", "Källa"),
        ),
    ),
    Tabellvy(
        "ark_jfr",
        "fran",
        (
            _dold("fid"),
            Kolumn("fran", "Lämningstyp"),
            Kolumn("till", "Jämför med"),
        ),
    ),
    Tabellvy(
        "ark_egenskapsvarde",
        "benamning",
        (
            _dold("fid"),
            Kolumn("benamning", "Lämningstyp"),
            Kolumn("typnamn", "Egenskap"),
            Kolumn("varde", "Värde"),
            _dold("ordning"),
        ),
    ),
)


def _lagerblock(xml: str, lager: str) -> tuple[int, int] | None:
    """Var i XML:en lagrets <maplayer> boerjar och slutar."""
    traff = xml.find(f"<layername>{lager}</layername>")
    if traff < 0:
        return None
    borjan = xml.rfind("<maplayer", 0, traff)
    slutet = xml.find("</maplayer>", traff)
    if borjan < 0 or slutet < 0:
        return None
    return borjan, slutet


def _aliasblock(vy: Tabellvy) -> str:
    rader = "\n".join(
        f'        <alias field="{kolumn.namn}" index="{nummer}"'
        f' name="{escape(kolumn.etikett)}"/>'
        for nummer, kolumn in enumerate(vy.kolumner)
    )
    return f"<aliases>\n{rader}\n      </aliases>"


def _tabellblock(vy: Tabellvy) -> str:
    rader = "\n".join(
        f'          <column type="field" name="{kolumn.namn}"'
        f' hidden="{1 if kolumn.dold else 0}"'
        f' width="{_LANGBREDD if kolumn.lang else -1}"/>'
        for kolumn in vy.kolumner
    )
    return (
        f'<attributetableconfig sortOrder="0" sortExpression="&quot;{vy.sortera}&quot;"'
        ' actionWidgetStyle="dropDown">\n'
        f"        <columns>\n{rader}\n"
        '          <column type="actions" hidden="1" width="-1"/>\n'
        "        </columns>\n"
        "      </attributetableconfig>"
    )


def _faltblock(vy: Tabellvy) -> str:
    """Flerradiga textrutor for de langa faelten, enradiga for resten.

    Det aer det haer som goer formulaervyn laesbar. Utan IsMultiline visas en
    1 200 tecken lang text i en enradig ruta.
    """
    rader = []
    for kolumn in vy.kolumner:
        if kolumn.dold:
            continue
        flerradig = "true" if kolumn.lang else "false"
        rader.append(
            f'        <field name="{kolumn.namn}" configurationFlags="NoFlag">\n'
            '          <editWidget type="TextEdit">\n'
            "            <config>\n"
            '              <Option type="Map">\n'
            f'                <Option type="bool" value="{flerradig}" name="IsMultiline"/>\n'
            '                <Option type="bool" value="false" name="UseHtml"/>\n'
            "              </Option>\n"
            "            </config>\n"
            "          </editWidget>\n"
            "        </field>"
        )
    inre = "\n".join(rader)
    return f"<fieldConfiguration>\n{inre}\n      </fieldConfiguration>"


def _ersatt(block: str, tagg: str, nytt: str) -> str:
    """Byter ut ett element, eller lagger till det om det saknas."""
    monster = rf"<{tagg}[^>]*/>|<{tagg}[^>]*>.*?</{tagg}>"
    if re.search(monster, block, re.DOTALL):
        return re.sub(monster, lambda _traff: nytt, block, count=1, flags=re.DOTALL)
    # Sist i lagret: QGIS laeser barnen pa namn, inte pa ordning.
    return block.rstrip() + f"\n      {nytt}\n    "


def satt_uppslagsvyer(xml: str) -> tuple[str, list[str]]:
    """Skriver alias, kolumnval och flerradighet pa uppslagslagren."""
    stallda: list[str] = []
    for vy in UPPSLAGSVYER:
        plats = _lagerblock(xml, vy.lager)
        if plats is None:
            continue
        borjan, slutet = plats
        block = xml[borjan:slutet]
        block = _ersatt(block, "aliases", _aliasblock(vy))
        block = _ersatt(block, "attributetableconfig", _tabellblock(vy))
        block = _ersatt(block, "fieldConfiguration", _faltblock(vy))
        xml = xml[:borjan] + block + xml[slutet:]
        stallda.append(vy.lager)
    return xml, stallda
