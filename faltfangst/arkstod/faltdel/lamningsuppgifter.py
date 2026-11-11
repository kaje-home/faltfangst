"""Vad RAA redan vet om en registrerad lamning, och som laag oanvant.

Lansuttaget bar tva tabeller verktyget aldrig rort:

    egenskap           17 184 rader i Blekinge
    ingaendelamning     1 059 rader

Den forsta sager vad varje registrerad lamning ar i detalj -- *Typ = Torp*,
*Form = Rund* -- och den andra vad en sammansatt lamning bestaar av: *13
Hagnad, 1 Fossil aker*. Bada hamnar i arbetsfilen vid uttaget och lastes
aldrig.

Det ar en lucka at ett hall. Verktyget **skapar** sammansatta lamningar ur
egna punkter och skriver "bestaende av 19 fangstgropar" i utkastet, men
laste aldrig motsvarande uppgift for de lamningar som redan finns. Oppnar
man ett gravfalt for revidering staar det ingenstans att det bestaar av sex
flatmarksgravar och trettio rojningsrosen -- det far man gaa till Fornsok
for att se, och i skogen finns inget Fornsok.

Uppgifterna ar RAA:s egna och skrivs aldrig av verktyget. De visas, inget
annat: den som reviderar ska se vad som staar i registret, och sjalv avgora
om det stammer med det hen har framfor sig.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Del:
    """En lamningstyp som ingaar i en sammansatt lamning, och hur manga."""

    lamningstyp: str
    antal: int | None

    def __str__(self) -> str:
        if self.antal is None:
            return self.lamningstyp
        return f"{self.antal} {self.lamningstyp.lower()}"


@dataclass
class Uppgifter:
    """Det registret bar om en lamning utover blankettens egna falt."""

    egenskaper: list[tuple[str, str]] = field(default_factory=list)
    delar: list[Del] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.egenskaper or self.delar)

    def text(self) -> str:
        """Uppgifterna som en manniska laser dem, eller tom strang."""
        rader = [f"{typ}: {varde}" for typ, varde in self.egenskaper]
        if self.delar:
            rader.append("Består av: " + ", ".join(str(d) for d in self.delar))
        return "\n".join(rader)


def _finns(anslutning: sqlite3.Connection, tabell: str) -> bool:
    return bool(
        anslutning.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (tabell,),
        ).fetchone()
    )


def uppgifter(anslutning: sqlite3.Connection, uuid: str | None) -> Uppgifter:
    """Egenskaper och ingaende lamningar for en lamning, ur uttaget.

    Tom for en lamning man just skapat: den finns inte i RAA:s tabeller, och
    dess egenskaper ar det man haaller pa att skriva.
    """
    ut = Uppgifter()
    if not uuid:
        return ut

    if _finns(anslutning, "egenskap"):
        ut.egenskaper = [
            (typ, varde)
            for typ, varde in anslutning.execute(
                "SELECT typ, varde FROM egenskap WHERE lamning_uuid = ?"
                " AND varde IS NOT NULL AND trim(varde) <> ''"
                " ORDER BY typ",
                (uuid,),
            )
        ]

    if _finns(anslutning, "ingaendelamning"):
        # Summerat per lamningstyp. RAA kan ha flera rader for samma typ --
        # de bar var sina egenskaper -- och "5 fossil aker, 1 fossil aker"
        # ar ingen upplysning utan en radbrytning som lackt igenom.
        ut.delar = [
            Del(lamningstyp=typ, antal=antal)
            for typ, antal in anslutning.execute(
                "SELECT lamningstyp, sum(antal) FROM ingaendelamning"
                " WHERE lamning_uuid = ? AND lamningstyp IS NOT NULL"
                " GROUP BY lamningstyp ORDER BY sum(antal) DESC, lamningstyp",
                (uuid,),
            )
        ]
    return ut


def _riktiga(varden):
    """Sallar bort brodtext som smugit sig in bland egenskapsvardena.

    Listans parser var en radlasare som stannade i vardelage och tog varje
    rad tills nasta etikett. Dar listan skriver ett forklarande stycke efter
    vardena hamnade de raderna bland dem, och i falt dok de upp i listrutan:
    "t Ovrig avser lamningar av typen giller, holkar, flak..." som ett
    valbart varde. Tva lamningstyper drabbade -- Fangstanlaggning ovrig och
    Lagenhetsbebyggelse.

    Parsern ar lagad, men en arbetsfil som redan tagits ut bar skrapet kvar,
    och ett nytt uttag ska inte behovas for att slippa det. Granserna ar
    listans egna: 456 akta varden ar 3-37 tecken, 1-4 ord, ingen slutar med
    punkt och ingen borjar gement.
    """
    return [
        v for v in varden
        if v and len(v) <= 45 and len(v.split()) <= 5
        and not v.endswith(".") and not v[0].islower()
    ]


def mojliga_egenskaper(
    anslutning: sqlite3.Connection, lamningstyp: str | None
) -> list[tuple[str, list[str]]]:
    """Vad lamningstypen kan vara, enligt lamningstypslistan.

    Sextiosex av listans 157 typer har egenskaper -- 45 en enda, 16 tva.
    En kolningsanlaggning kan vara kolbotten liggmila, kolbotten resmila,
    kolningsgrop eller kolugn, och det ar det ordforrad beskrivningen ska
    hamtas ur.

    Tabellerna ligger i arbetsfilen med `ark_`-prefix, som resten av listan.
    """
    if not lamningstyp:
        return []
    # Arbetsfilens kopia binder egenskapsvardet till benamning och typnamn;
    # lamningstypsdatabasen binder det till ett id. Bada finns, sa fragan
    # far folja den tabell som ar framme.
    prefix = "ark_" if _finns(anslutning, "ark_egenskapstyp") else ""
    if not _finns(anslutning, f"{prefix}egenskapstyp"):
        return []
    ut: list[tuple[str, list[str]]] = []
    if prefix:
        for (typnamn,) in anslutning.execute(
            "SELECT typnamn FROM ark_egenskapstyp WHERE benamning = ?"
            " ORDER BY ordning",
            (lamningstyp,),
        ):
            varden = _riktiga([
                varde
                for (varde,) in anslutning.execute(
                    "SELECT varde FROM ark_egenskapsvarde"
                    " WHERE benamning = ? AND typnamn = ? ORDER BY ordning",
                    (lamningstyp, typnamn),
                )
            ])
            if varden and typnamn:
                ut.append((typnamn, varden))
        return ut

    for tid, typnamn in anslutning.execute(
        "SELECT id, typnamn FROM egenskapstyp WHERE benamning = ?"
        " ORDER BY ordning",
        (lamningstyp,),
    ):
        varden = _riktiga([
            varde
            for (varde,) in anslutning.execute(
                "SELECT varde FROM egenskapsvarde"
                " WHERE egenskapstyp = ? ORDER BY ordning",
                (tid,),
            )
        ])
        if varden and typnamn:
            ut.append((typnamn, varden))
    return ut
