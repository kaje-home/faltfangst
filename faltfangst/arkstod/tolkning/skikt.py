"""Uteslutningsskiktet, last ur TOML.

Typbestamningsfel ar allvarligare an bedomningsfel: vissa typer far
fornlamningsstatus automatiskt, och da sker ingen rekvisitprovning som kan
fanga felet. Kravet pa uteslutning ar darfor hogre for dem, inte lagre.

En post kan hanga pa en lamningstyp -- eller pa ett egenskapsvarde inom den.
Det ar ingen finess utan en nodvandighet. Stenstrang ar inget uppslagsord i
listan utan Hagnad med egenskapsvardet Typ = Stenstrang, och det ar vardet som
ger automatisk fornlamningsstatus. Risken sitter i vardet, inte i typen.

Skiktet pastar aldrig ett utfall. Det staller fragor och redovisar
sarskiljande drag. Vad lamningen ar avgors i falt av den som star dar.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from arkstod import lan as lansmodul
from arkstod.lamningstyper.uppslag import slaupp

PROJEKTROT = Path(__file__).resolve().parent.parent.parent
TOLKNINGSMAPP = PROJEKTROT / "tolkning"

# Samma nivaer som korpusens kallforteckning anvander. Att halla dem lika ar
# poangen: en hanvisning ska ga att folja tillbaka till ratt sorts text.
NIVAER = {
    "bindande",
    "normerande",
    "tolkande",
    "regional tillämpning",
    "regional erfarenhet",
}


@dataclass
class Uteslutning:
    """Vad som maste uteslutas innan ett typval star fast."""

    lamningstyp: str
    uteslut: list[str] = field(default_factory=list)
    fragor: list[str] = field(default_factory=list)
    sarskiljande: str = ""
    egenskapstyp: str = ""
    egenskapsvarde: str = ""
    kalla: str = ""
    niva: str = ""
    lan: str = ""

    @property
    def galler_egenskapsvarde(self) -> bool:
        return bool(self.egenskapsvarde)

    def rubrik(self) -> str:
        if self.galler_egenskapsvarde:
            return f"{self.lamningstyp} ({self.egenskapstyp}: {self.egenskapsvarde})"
        return self.lamningstyp

    def som_kontextvarning(self) -> str:
        """Raden som ska sta passivt i faltformularet vid typval."""
        delar = [self.rubrik()]
        if self.uteslut:
            delar.append("uteslut: " + ", ".join(self.uteslut))
        if self.fragor:
            delar.append(" ".join(self.fragor))
        return " — ".join(delar)


@dataclass
class Beskrivningstillagg:
    """Ett fortydligande till Exempelsamlingens beskrivningsprincip.

    Exempelsamlingen sager for Kolningsanlaggning bara "anlaggningens form,
    storlek" och lamnar oppet om vallen raknas in. For Fangstgrop ar den
    daremot explicit: "storlek (exklusive omgivande vall)". Falthandboken
    sluter luckan och sager det som en regel med namngivna undantag -- "Det
    stora undantaget ar gropar och kolbottnar".

    Tillagget star darfor bredvid principen, aldrig i stallet for den, och
    bar sin egen kalla. RAA:s ord och handbokens ska inte ga att forvaxla.
    """

    lamningstyp: str
    text: str
    egenskapstyp: str = ""
    egenskapsvarde: str = ""
    kalla: str = ""
    niva: str = ""
    lan: str = ""

    def rubrik(self) -> str:
        if self.egenskapsvarde:
            return f"{self.lamningstyp} ({self.egenskapstyp}: {self.egenskapsvarde})"
        return self.lamningstyp


@dataclass
class Skikt:
    """Ett skikt: nationellt, eller for ett lan."""

    lan: str
    niva: str
    kalla: str
    uteslutningar: list[Uteslutning] = field(default_factory=list)
    beskrivningstillagg: list[Beskrivningstillagg] = field(default_factory=list)
    fil: Path | None = None

    @property
    def nationellt(self) -> bool:
        return not self.lan


def _stad(text: str) -> str:
    return " ".join(text.split())


def las_skikt(fil: Path | str) -> Skikt:
    """Laser och validerar ett skikt.

    tomllib importeras har och inte pa modulniva: QGIS LTR kan ha Python 3.9,
    och faltdelen laser skiktet ur databasen i stallet for ur TOML.
    """
    import tomllib

    fil = Path(fil)
    data = tomllib.loads(fil.read_text(encoding="utf-8"))
    lan_ = lansmodul.normalisera(data.get("lan", ""))
    niva = data.get("niva", "")
    kalla = data.get("kalla", "")

    skikt = Skikt(
        lan=lan_,
        niva=niva,
        kalla=kalla,
        uteslutningar=[
            Uteslutning(
                lamningstyp=post["lamningstyp"],
                uteslut=[_stad(rad) for rad in post.get("uteslut", [])],
                fragor=[_stad(rad) for rad in post.get("fragor", [])],
                sarskiljande=_stad(post.get("sarskiljande", "")),
                egenskapstyp=post.get("egenskapstyp", ""),
                egenskapsvarde=post.get("egenskapsvarde", ""),
                kalla=post.get("kalla", kalla),
                niva=post.get("niva", niva),
                lan=lan_,
            )
            for post in data.get("uteslutning", [])
        ],
        beskrivningstillagg=[
            Beskrivningstillagg(
                lamningstyp=post["lamningstyp"],
                text=_stad(post["text"]),
                egenskapstyp=post.get("egenskapstyp", ""),
                egenskapsvarde=post.get("egenskapsvarde", ""),
                kalla=post.get("kalla", kalla),
                niva=post.get("niva", niva),
                lan=lan_,
            )
            for post in data.get("beskrivningstillagg", [])
        ],
        fil=fil,
    )
    validera(skikt)
    return skikt


def validera(skikt: Skikt) -> None:
    plats = skikt.fil.name if skikt.fil else (skikt.lan or "nationellt")

    if skikt.lan and not lansmodul.ar_lan(skikt.lan):
        raise ValueError(f"{plats}: okänt län {skikt.lan!r}")
    if skikt.niva not in NIVAER:
        raise ValueError(
            f"{plats}: okänd nivå {skikt.niva!r}; "
            f"tillåtna: {', '.join(sorted(NIVAER))}"
        )
    if not (skikt.uteslutningar or skikt.beskrivningstillagg):
        raise ValueError(f"{plats}: skiktet är tomt")

    for post in skikt.uteslutningar:
        if not post.kalla:
            raise ValueError(f"{plats}: {post.lamningstyp} saknar källa")
        if post.niva not in NIVAER:
            raise ValueError(f"{plats}: {post.lamningstyp} har okänd nivå")
        if not post.uteslut and not post.fragor and not post.sarskiljande:
            raise ValueError(
                f"{plats}: {post.lamningstyp} säger ingenting — "
                "en post utan uteslutning, fråga eller särskiljande drag "
                "är bara en rubrik"
            )
        if post.egenskapsvarde and not post.egenskapstyp:
            raise ValueError(
                f"{plats}: {post.rubrik()} anger egenskapsvärde utan egenskapstyp"
            )

    for post in skikt.beskrivningstillagg:
        if not post.kalla:
            raise ValueError(f"{plats}: tillägget för {post.rubrik()} saknar källa")
        if not post.text:
            raise ValueError(f"{plats}: tillägget för {post.rubrik()} är tomt")
        if post.egenskapsvarde and not post.egenskapstyp:
            raise ValueError(
                f"{plats}: {post.rubrik()} anger egenskapsvärde utan egenskapstyp"
            )


def las_alla(mapp: Path | str = TOLKNINGSMAPP) -> list[Skikt]:
    return [las_skikt(fil) for fil in sorted(Path(mapp).glob("*.toml"))]


def kontrollera_mot_listan(
    skikt: list[Skikt], anslutning: sqlite3.Connection
) -> list[str]:
    """Att varje post hanger pa nagot som finns i Lamningstypslistan.

    Fagata ar exemplet: ordet ar inarbetat men ar inget uppslagsord i
    listan, utan ett varde under Fardvag och Hagnad. En uteslutningsregel
    for en typ som inte finns ar inte bara oanvandbar -- den visar att nagon
    skrivit ur minnet i stallet for ur listan.
    """
    problem: list[str] = []
    for ett_skikt in skikt:
        plats = ett_skikt.fil.name if ett_skikt.fil else ett_skikt.lan
        for post in ett_skikt.uteslutningar:
            uppslag = slaupp(anslutning, post.lamningstyp)
            if uppslag is None:
                problem.append(
                    f"{plats}: {post.lamningstyp} finns inte i Lämningstypslistan"
                )
                continue
            if not post.egenskapsvarde:
                continue
            varden = {
                varde
                for typnamn, _flervard, lista in uppslag.egenskapstyper
                if typnamn == post.egenskapstyp
                for varde in lista
            }
            if post.egenskapsvarde not in varden:
                problem.append(
                    f"{plats}: {post.lamningstyp} har inget egenskapsvärde "
                    f"{post.egenskapsvarde!r} under {post.egenskapstyp!r}"
                )
    return problem


def uteslutningar_for(
    skikt: list[Skikt], lamningstyp: str, lan: str = ""
) -> list[Uteslutning]:
    """Posterna for en lamningstyp: nationella forst, darefter lanets egna."""
    sokt_lan = lansmodul.normalisera(lan) if lan else ""
    traffar = [
        post
        for ett_skikt in skikt
        for post in ett_skikt.uteslutningar
        if post.lamningstyp == lamningstyp
        and (not post.lan or not sokt_lan or post.lan == sokt_lan)
    ]
    return sorted(traffar, key=lambda post: (bool(post.lan), post.rubrik()))


def las_ur_databas(anslutning: sqlite3.Connection) -> list[Skikt]:
    """Skiktet som det bakats in i lamningstypsdatabasen vid bygget.

    Faltdelen gaar den har vagen. Den behover da bara sqlite3, och kan koras
    i vilken QGIS-installation som helst utan att bry sig om Python-version
    eller om TOML-filerna foljt med.
    """
    per_lan: dict[str, Skikt] = {}

    def skikt_for(lan: str, niva: str, kalla: str) -> Skikt:
        if lan not in per_lan:
            per_lan[lan] = Skikt(lan=lan, niva=niva, kalla=kalla)
        return per_lan[lan]

    for rad in anslutning.execute(
        "SELECT lamningstyp, egenskapstyp, egenskapsvarde, uteslut, fragor,"
        " sarskiljande, kalla, niva, lan FROM uteslutning ORDER BY id"
    ).fetchall():
        skikt_for(rad[8], rad[7], rad[6]).uteslutningar.append(
            Uteslutning(
                lamningstyp=rad[0],
                egenskapstyp=rad[1],
                egenskapsvarde=rad[2],
                uteslut=[del_ for del_ in rad[3].split(chr(10)) if del_],
                fragor=[del_ for del_ in rad[4].split(chr(10)) if del_],
                sarskiljande=rad[5],
                kalla=rad[6],
                niva=rad[7],
                lan=rad[8],
            )
        )

    for rad in anslutning.execute(
        "SELECT lamningstyp, egenskapstyp, egenskapsvarde, text, kalla, niva, lan"
        " FROM beskrivningstillagg ORDER BY id"
    ).fetchall():
        skikt_for(rad[6], rad[5], rad[4]).beskrivningstillagg.append(
            Beskrivningstillagg(
                lamningstyp=rad[0],
                egenskapstyp=rad[1],
                egenskapsvarde=rad[2],
                text=rad[3],
                kalla=rad[4],
                niva=rad[5],
                lan=rad[6],
            )
        )

    # Nationellt forst, som uteslutningar_for redan sorterar.
    return [per_lan[lan] for lan in sorted(per_lan, key=lambda namn: (bool(namn), namn))]
