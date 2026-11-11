"""Vem som gjort verktyget, vilken version det ar, och vad det svarar utifran.

Den sista fragan ar den som betyder nagot i falt. Verktyget sager att en
fangstgrop ska matas i bottenplan och att en fabod utan akerbruk inte ar
fornlamning -- och de svaren galler bara sa lange listan och handboken sager
sa. Nasta version av lamningstypslistan kan andra dem.

Darfor namner rutan inte bara programversionen utan ocksa korpusversionerna.
De staar redan i databasen, skrivna vid bygget; harifran lases de bara ut.
"""

from __future__ import annotations

import sqlite3

# Tabellerna som bar en kalla, och vad de styr. Ordningen ar den som
# hierarkin har: listan ager kombinationerna, exempelsamlingen ordalydelsen,
# falthandboken undantagen.
KALLTABELLER = (
    ("beskrivningsprincip", "beskrivningarnas form"),
    ("beskrivningsexempel", "färdiga exempel"),
    ("uteslutning", "uteslutningar och frågor"),
)


def pluginzipnamn() -> str:
    """Vad pluginens zip heter. Bygget, utskicket och proven fragar har.

    Zippen heter som pluginens mapp och likadant i varje version. Da gaar
    den att lanka till med en fast adress -- utgavans senaste zip -- och
    bruksanvisningen kan namnge filen utan att bli fel vid nasta version.
    Vilken version en zip bar staar i dess metadata.txt.
    """
    return "faltfangst.zip"


def las_metadata(sokvag) -> dict:
    """Plockar ut namn, version och upphovsman ur pluginens metadata.txt.

    En enda sanning om versionen. Skrivs den in i koden ocksa staar de tva i
    otakt vid forsta slarvet, och da ljuger rutan.
    """
    uppgifter = {}
    try:
        with open(sokvag, encoding="utf-8") as fil:
            for rad in fil:
                rad = rad.strip()
                # Sektionsrubrik eller kommentar. Filen bar kommentarer sedan
                # tracker och repository togs bort, och en kommentar med ett
                # likhetstecken i hade annars blivit ett falt.
                if not rad or rad[0] in "[#;":
                    continue
                if "=" in rad:
                    nyckel, _, varde = rad.partition("=")
                    uppgifter[nyckel.strip()] = varde.strip()
    except OSError:
        return {}
    return uppgifter


def korpuskallor(anslutning: sqlite3.Connection) -> list[tuple[str, str]]:
    """Vilka dokument databasen byggts ur, och vad var och ett styr."""
    kallor: list[tuple[str, str]] = []
    try:
        rad = anslutning.execute(
            "SELECT filnamn, listversion, hamtdatum FROM kalla WHERE id = 1"
        ).fetchone()
    except sqlite3.Error:
        return kallor
    if rad:
        filnamn, listversion, hamtdatum = rad
        kallor.append(
            (f"Lämningstypslistan {listversion} ({hamtdatum})",
             "lämningstyper och kombinationer"),
        )
    for tabell, styr in KALLTABELLER:
        try:
            namn = [
                n for (n,) in anslutning.execute(
                    f"SELECT DISTINCT kalla FROM {tabell} WHERE kalla IS NOT NULL"
                )
            ]
        except sqlite3.Error:
            continue
        for n in sorted(namn):
            if n not in [k for k, _ in kallor]:
                kallor.append((n, styr))
    return kallor


def om_texten(metadata: dict, kallor: list[tuple[str, str]]) -> str:
    """Rutans text. Kort, och utan en enda uppgift som inte gaar att styrka."""
    namn = metadata.get("name", "Fältfångst")
    rader = [f"{namn} {metadata.get('version', '')}".strip()]
    # Statusen laser vi ur metadata av samma skal som versionen: en enda
    # sanning. Skrivs "beta" in har ocksa staar de tva i otakt vid forsta
    # slarvet. Fragan kommer fran falt -- "vad ar det har for nagot, ar det
    # fardigt?" -- och da ska rutan svara, inte tiga.
    if metadata.get("experimental", "").strip().lower() == "true":
        rader.append("BETAVERSION — inte färdig, kontrollera det som"
                     " ska till Fornreg")
    if metadata.get("author"):
        rader.append(f"Av {metadata['author']}")
    if metadata.get("email"):
        rader.append(metadata["email"])
    if not kallor:
        return chr(10).join(rader)
    rader.append("")
    rader.append("Verktyget svarar utifrån:")
    rader.extend(f"  • {namn} — {styr}" for namn, styr in kallor)
    rader.append("")
    rader.append(
        "Ändras något av dem ändras svaren. Bygg om databasen när en ny"
        " version kommit."
    )
    return chr(10).join(rader)
