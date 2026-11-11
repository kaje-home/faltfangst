"""Faltfangstkolumner som verktyget lagger till i lamningar-GPKG:n.

RAA:s lansuttag har inga falt for det inventeraren ser men registret inte
fragar efter. Migreringsskriptet lagger redan till en handfull -- Kommentar,
Skadebesk, veg, Karta, matmet -- och alderindicierna hor till samma familj.

Tillagget maste vara idempotent och overleva en ny sasongskorning: uttaget
hamtas om varje ar och kolumnerna forsvinner da med det. Att lagga till dem
via ALTER TABLE vid varje export ar darfor inte en genvag utan sjalva
konstruktionen.

Alderindicierna ar inte obligatoriska och far inte bli det. De ar noteringar
gjorda i forbifarten -- fem kryssrutor som kostar under fem sekunder. Ett
obligatoriskt falt hade gjort dem till nagot man maste svara pa, och da hade
de inte hunnit med i falt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

KALLA = "Fälthandbok i arkeologisk inventering 2.0 (2023-11-28), Jamtli. CC BY."


@dataclass(frozen=True)
class Faltkolumn:
    """En kolumn verktyget behover, och varfor."""

    namn: str
    typ: str
    etikett: str
    forklaring: str


# Kolumnnamnen ar ASCII. Svenska tecken i identifierare har bitit i QGIS
# plugin-arbete forr, och ett kolumnnamn ar en identifierare i uttryck.
ALDERSINDICIER: tuple[Faltkolumn, ...] = (
    Faltkolumn(
        "ind_overtorvade_stubbar",
        "INTEGER",
        "Övertorvade stubbar",
        "Stubbar som hunnit torva över talar för tidsdjup. Ingår i "
        "stubbresonemanget för liggmilekolbottnar.",
    ),
    Faltkolumn(
        "ind_mosstackning",
        "INTEGER",
        "Mosstäckning",
        "Lav- och mosstäckning på stenar ger tidsdjup — och saknad lav på "
        "brottytor pekar åt motsatt håll.",
    ),
    Faltkolumn(
        "ind_stenar_nedsjunkna",
        "INTEGER",
        "Stenar nedsjunkna",
        "Nedsjunkna stenar och humusbildning mellan dem skiljer en gammal "
        "stensamling från ett sentida upplag.",
    ),
    Faltkolumn(
        "ind_sprangsten",
        "INTEGER",
        "Sprängsten",
        "Skarpkantad sten med färska brottytor, jämn fraktion och ibland "
        "borrhål. Talar mot forntida ursprung.",
    ),
    Faltkolumn(
        "ind_sentida_material",
        "INTEGER",
        "Sentida material i sonden",
        "Vad jordsonden får upp: tegel, glas, plast, sågspån.",
    ),
)


# Faltfangstfalt som migreringen redan lagger till. De ar verktygets egna --
# RAA fyller dem aldrig -- och hor darfor hemma har, inte i ett skript som
# ocksa ager projektfilen. Typerna ar desamma som migreringen anvander, sa att
# en befintlig uppsattning inte far en annan kolumn an den redan har.
FALTFANGSTKOLUMNER: tuple[Faltkolumn, ...] = (
    Faltkolumn("Kommentar", "TEXT(250)", "Kommentar", "Fri anteckning."),
    Faltkolumn(
        "Skadebesk", "TEXT(250)", "Skadebeskrivning", "Krävs vid åverkan."
    ),
    Faltkolumn(
        "veg",
        "TEXT(250)",
        "Vegetation på lämningen",
        "Växtlighet direkt på lämningen, främst träd och buskar — inte "
        "växtligheten på platsen, den hör till Terräng kring lämning. "
        "Fornreg 4.0: ”Ange alltid art på växten och uppge antal eller om "
        "vegetationen är tät eller gles. Ange gärna (uppskattad) ålder på "
        "träd. Gräs-, moss- och örtvegetation anges inte, om inte särskilda "
        "skäl finns.” Skälet är att träden kan ha skadat lämningen, och att "
        "de hjälper den som ska hitta tillbaka.",
    ),
    Faltkolumn("ovrigt", "TEXT(250)", "Övrigt", "Det som inte hör någon annanstans."),
    Faltkolumn("Karta", "TEXT(100)", "Karta", "Kartunderlag som använts."),
    Faltkolumn(
        "matmet",
        "TEXT(100)",
        "Mätmetod",
        "Ger medelfelsdefault: GPS ±7 m, DGPS ±2 m, RTK ±0,05 m.",
    ),
    Faltkolumn(
        "Granskningsdatum",
        "DATE",
        "Granskningsdatum",
        "Den dag man stod vid lämningen. Både nyregistrering och revidering "
        "är ett besök, så fältet sätts till dagens datum så fort man ändrat "
        "något annat i formuläret. Skriver man in ett datum för hand — man "
        "var på platsen i går — ska det skrivas sist.",
    ),
    Faltkolumn(
        "medelfel",
        "REAL",
        "Medelfel (m)",
        "Följer av mätmetoden: GPS ±7 m, DGPS ±2 m, RTK ±0,05 m. Sätts som "
        "default så att det inte behöver skrivas in vid varje registrering.",
    ),
    Faltkolumn(
        "TID",
        "INTEGER",
        "TID",
        "Löpnummer, unikt och obligatoriskt. Nästa lediga nummer i det egna "
        "geometrilagret sätts av sig självt — även när man reviderar en "
        "äldre registrering, för den har inget. Ett nummer som redan står "
        "där rörs aldrig: det ska gå att skriva om för att lägga en lämning "
        "mellan två andra i ordningen.",
    ),
    Faltkolumn(
        "ingar_i",
        "INTEGER",
        "Ingår i",
        "Systemets löpnummer, för en lämning som blivit del av en sammansatt "
        "lämningstyp. I fält prickas enskilda fångstgropar; visar det sig på "
        "kontoret att de bildar ett fångstgropssystem blir systemet lämningen "
        "och groparna dess delar — Fornsök skriver det som ”Lämningen består "
        "av: Fångstgrop, antal 19”. Groparna levereras då inte som egna "
        "lämningar, och det är den här kolumnen som säger det.",
    ),
    Faltkolumn(
        "autotext",
        "INTEGER",
        "Fortsätt på samma text",
        "Kryssrutan vid beskrivningen. Är den ikryssad börjar NÄSTA "
        "nyregistrerade lämning med den här lämningens beskrivning — för när "
        "man står inför många av samma sort. Den är en kolumn och inte en "
        "inställning därför att QGIS bara kopplar widgetar som svarar mot ett "
        "fält, och därför att valet då följer med lämningen: kryssar man i "
        "den på den första kolbottnen står den kvar på nästa.",
    ),
)

# Allt verktyget lagger till i ett uttag.
#
# Aldersindicierna ingaar inte langre. De fem kryssrutorna satt pa en egen
# flik i formularet och fylldes aldrig i -- noll av 25 820 lamningar i det
# jamtlandska uttaget hade ett enda varde. Resonemanget om att de skulle
# kosta under fem sekunder holl inte i falt, och en flik som ingen anvander
# ar en flik att bladdra forbi.
#
# Kolumnerna tas inte bort ur befintliga filer. Sammanfogningen behaller
# varje lokal kolumn som finns i den gamla filen men saknas i den nya, sa
# den som redan har dem far dem kvar -- medan en ny uppsattning slipper dem.
ALLA_EGNA: tuple[Faltkolumn, ...] = FALTFANGSTKOLUMNER


def _kolumner(anslutning: sqlite3.Connection, tabell: str) -> set[str]:
    return {
        rad[1] for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")').fetchall()
    }


def sakerstall_kolumner(
    anslutning: sqlite3.Connection,
    tabeller: list[str],
    kolumner: tuple[Faltkolumn, ...] = ALDERSINDICIER,
) -> dict[str, list[str]]:
    """Lagger till de kolumner som saknas. Rör aldrig befintlig data.

    Returnerar vilka kolumner som faktiskt lades till per tabell -- tom lista
    betyder att de redan fanns.
    """
    tillagda: dict[str, list[str]] = {}
    for tabell in tabeller:
        fanns = _kolumner(anslutning, tabell)
        nya = [kolumn for kolumn in kolumner if kolumn.namn not in fanns]
        for kolumn in nya:
            anslutning.execute(
                f'ALTER TABLE "{tabell}" ADD COLUMN "{kolumn.namn}" {kolumn.typ}'
            )
        tillagda[tabell] = [kolumn.namn for kolumn in nya]
    return tillagda
