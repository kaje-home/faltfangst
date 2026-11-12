"""Sammansatta lamningstyper: att hitta dem bland punkterna man prickat i falt.

I falt registreras enskilda fangstgropar. Om de bildar ett system vet man
inte forran man sett dem tillsammans, och ytan ritas darfor pa kontoret. Det
gaar att rakna fram -- men bara till en viss grans, och gransen staar i
lamningstypslistans egen definition:

    Omrade med minst fem fangstgropar dar det av terrangforhallanden framgar
    att groparna bildar en funktionell enhet.

Meningen delar sig i tva halvor som hor hemma pa var sin sida om verktyget:

* **Raknebart** -- minst fem gropar, och deras inbordes avstand.
* **Bedomning** -- "av terrangforhallanden framgar ... funktionell enhet".

Verktyget gor den forsta halvan och lamnar den andra. Det foreslar klungor;
det avgor ingenting.

Avstandet ar en grundregel med undantag, och undantaget gors per system
-----------------------------------------------------------------------

Kommentaren till samma typ sager att avstandet **kan overstiga 50 meter** om
topografin visar att groparna hor ihop. Ett verkligt system i samma lan --
L1946:3142 i Naskott, 19 gropar over 872 m -- har inbordes avstand pa
14-110 m. En kedjning vid 50 m delar det i bitar.

Det gaar inte att laga med ett hogre tal for hela korningen. Femtio meter ar
grundregeln, och undantaget hor till *ett* system: har sager topografin att
groparna hor ihop, dar sager den att de inte gor det. En ratt som staller om
hela lanet pa en gaang skulle byta ut den bedomningen mot en inställning.

Darfor tva vagar in:

* **Genomgangen** kedjar vid grundregelns 50 m och namner de klungor som
  ligger nara varandra -- inte som fel, utan som de stallen dar topografin
  behover tittas pa.
* **Markeringen** later arkeologen peka ut groparna sjalv, pa kartan med
  terrangen framme, och da galler inget avstandskrav alls. Bedomningen gors
  dar den hor hemma.

Antalet ar en annan sak. "Minst fem" ar ett tal i listan och inte en
bedomning, sa det galler bada vagarna.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from arkstod.faltdel.mattregel import axel, langdmatt

@dataclass(frozen=True)
class Regel:
    """Vad listan sager om en sammansatt typ, i tal.

    Talen staar inte i koden. De laeses ur lamningstypslistan, som varje
    arbetsfil bar med sig -- forst stod de som konstanter har med ett prov
    som holl dem mot definitionstexten, och det var en avskrift for mycket.
    Listan ar kallan; koden ska fraaga den.

    `kalla` ar meningen talen kommer ur. Den visas for den som ska avgora,
    for tjugo meter i en definition och femtio i en kommentar betyder inte
    riktigt samma sak -- se `regler`.
    """

    sammansatt: str
    ingaende: tuple[str, ...]
    minsta_antal: int
    # Avstandet som definitionen eller kommentaren namner. Ett forval att
    # stalla in efter, inte en grans att lita pa.
    normalt_avstand: int
    kalla: str = ""

    @property
    def enda_ingaende(self) -> str:
        """Typnamnet nar det bara finns ett, annars tom strang."""
        return self.ingaende[0] if len(self.ingaende) == 1 else ""

    @property
    def har_begransningsyta(self) -> bool:
        """Om systemets yttre begransning ska ritas som en yta."""
        return self.sammansatt not in UTAN_BEGRANSNINGSYTA


# Sammansatta typer som inte far nagon yttre begransningsyta.
#
# Handledningen for Fornreg 4.0, s. 50, om lamningar over 20 meter: *Undantag
# ar fardvagsystem som ska besta av minst tva fardvagar. Dessa ska inte
# registreras med en yta for den yttre begransningen, utan endast med linjer.*
#
# Exempelsamlingen s. 87 sager samma sak om delarna: *pa kartan ritas vagar
# alltid in som linjer i hela sin sträckning och aldrig som omraden.*
#
# Listan ar en upprakning och inte en harledning, for undantaget staar i
# handledningen och inte i lamningstypslistan -- den senare vet inte att
# fardvagssystemet skiljer sig fran gravfaltet.
UTAN_BEGRANSNINGSYTA: tuple[str, ...] = ("Färdvägssystem",)


# "minst fem", som listan skriver antalet.
RAKNEORD = {
    "två": 2, "tre": 3, "fyra": 4, "fem": 5, "sex": 6,
    "sju": 7, "atta": 8, "åtta": 8, "nio": 9, "tio": 10,
}

_MINST = re.compile(r"minst (" + "|".join(RAKNEORD) + r")\b", re.IGNORECASE)
_AVSTAND = re.compile(r"(\d+)\s*(?:m|meter)\b")


def regler(anslutning) -> dict[str, Regel]:
    """Reglerna for sammansatta typer, laesta ur lamningstypslistan.

    Tjugoen av listans tjugotva sammansatta typer bar bade ett antal och ett
    avstand i sin egen text:

        Gravfalt: Omrade med minst fem forhistoriska gravanlaggningar med
        ett inbordes avstand av hogst 20 m ...

        Fangstgropssystem: ... kan det inbordes avstandet mellan groparna
        overstiga 50 meter om det av topografin ... framgar att groparna
        hor ihop.

    **De tva talen betyder inte riktigt samma sak.** Gravfaltets tjugo ar ett
    kriterium; fangstgropssystemets femtio ar ett undantag fran en underforstadd
    norm. Bada duger som utgangspunkt for att kedja ihop punkter, men verktyget
    far inte laatsas att de ar samma sorts regel -- darfor bar varje regel med
    sig meningen den kommer ur, och den visas for den som ska avgora.

    Tabellerna finns bade i lamningstypsdatabasen och, med `ark_`-prefix, i
    varje arbetsfil.
    """
    prefix = _prefix(anslutning)
    if prefix is None:
        return {}

    ingaende: dict[str, list[str]] = {}
    for sammansatt, del_ in anslutning.execute(
        f"SELECT sammansatt, ingaende FROM {prefix}ingaende_typ"
    ):
        ingaende.setdefault(sammansatt, []).append(del_)

    ut: dict[str, Regel] = {}
    for benamning, definition, kommentar in anslutning.execute(
        f"SELECT benamning, definition, coalesce(kommentar, '')"
        f" FROM {prefix}lamningstyp WHERE sammansatt = 1"
    ):
        text = f"{definition} {kommentar}"
        antal = _MINST.search(text)
        avstand = _AVSTAND.search(text)
        if not (antal and avstand and ingaende.get(benamning)):
            continue
        mening = next(
            (
                bit.strip()
                for bit in re.split(r"(?<=\.)\s+", text)
                if _AVSTAND.search(bit)
            ),
            text.strip(),
        )
        ut[benamning] = Regel(
            sammansatt=benamning,
            ingaende=tuple(sorted(ingaende[benamning])),
            minsta_antal=RAKNEORD[antal.group(1).lower()],
            normalt_avstand=int(avstand.group(1)),
            kalla=mening,
        )
    return ut


def _prefix(anslutning) -> str | None:
    """`ark_` i en arbetsfil, tomt i lamningstypsdatabasen."""
    namn = {
        rad[0]
        for rad in anslutning.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    for prefix in ("ark_", ""):
        if f"{prefix}lamningstyp" in namn and f"{prefix}ingaende_typ" in namn:
            return prefix
    return None


# Hur langt utanfor groparna begransningslinjen gaar. Beskrivningsprincipen
# sager att groparna "sammanbinds till ett system med en omgivande
# begransningslinje" men inte hur brett; tio meter at bada hallen ar ett
# arbetsmatt, valt i falt.
MARGINAL = 10


@dataclass(frozen=True)
class Punkt:
    """En prickad lamning: identitet och plats i SWEREF 99 TM."""

    fid: int
    x: float
    y: float
    # Punktens egen lamningstyp. En sammansatt typ kan ha manga ingaende --
    # Gravfalt har tolv -- och da gaar det inte att namna dem ur regeln.
    typ: str = ""

    def till(self, annan: "Punkt") -> float:
        return math.hypot(self.x - annan.x, self.y - annan.y)


@dataclass
class Matt:
    """Det som gaar att mata upp ur en klunga -- och som beskrivningen vill ha."""

    antal: int
    langd: int
    riktning: str
    minsta_avstand: int
    storsta_avstand: int
    # Samma tva uppgifter som `langd` och `riktning`, oavrundade. Texten
    # skrivs ur dem -- se `langdtext` -- sa att avrundningen gors pa ett
    # stalle och inte en gaang har och en gaang dar.
    utstrackning: float = 0.0
    barning: float = 0.0


@dataclass
class Kandidat:
    punkter: list[Punkt]
    matt: Matt
    kanter: list[tuple[Punkt, Punkt]]


@dataclass
class Rapport:
    """Vad genomgangen fann, och vad den inte vagade svara pa."""

    kandidater: list[Kandidat] = field(default_factory=list)
    # Klungor som haller ihop men inte nar antalet. De ar inte system, och
    # de ar just dar bedomningen behovs -- darfor namns de.
    for_faa: list[list[Punkt]] = field(default_factory=list)
    # Par av klungor som ligger nara varandra. Kommentaren tillater att
    # avstandet overstiger forvalet, sa narheten ar en fraaga och inget fel.
    narliggande: list[tuple[int, int, int]] = field(default_factory=list)


def klungor(punkter: list[Punkt], avstand: float) -> list[list[Punkt]]:
    """Delar punkterna i klungor dar varje grop nar nagon annan i klungan.

    Enkellankning, och det ar med flit: ett fangstgropssystem ar en kedja
    over en terrangpassage, inte en rund hop. Ett matt fran mittpunkten hade
    delat langa system pa mitten.
    """
    kvar = list(punkter)
    resultat: list[list[Punkt]] = []
    while kvar:
        klunga = [kvar.pop()]
        vaxte = True
        while vaxte:
            vaxte = False
            for punkt in list(kvar):
                if any(punkt.till(medlem) <= avstand for medlem in klunga):
                    klunga.append(punkt)
                    kvar.remove(punkt)
                    vaxte = True
        resultat.append(sorted(klunga, key=lambda p: p.fid))
    return sorted(resultat, key=lambda k: (-len(k), k[0].fid))


def kanter(klunga: list[Punkt]) -> list[tuple[Punkt, Punkt]]:
    """Kortaste natet som binder ihop groparna -- ett minsta uppspannande trad.

    Det ar "sammanbinds groparna till ett system" ur beskrivningsprincipen,
    och det ar ocksa vad ytan sedan laggs runt. Ett trad och inte en kedja:
    system grenar sig ibland, och en kedja hade da tvingat fram en omvag.
    """
    if len(klunga) < 2:
        return []
    inne = [klunga[0]]
    ute = list(klunga[1:])
    resultat: list[tuple[Punkt, Punkt]] = []
    while ute:
        bast = min(
            ((a, b) for a in inne for b in ute), key=lambda par: par[0].till(par[1])
        )
        resultat.append(bast)
        inne.append(bast[1])
        ute.remove(bast[1])
    return resultat


def _huvudriktning(punkter: list[Punkt]) -> tuple[float, str]:
    """Klungans huvudaxel som barning i grader, och som vaderstreck.

    Axeln raknas ur spridningen: den riktning dar groparna ligger mest
    utdragna. Det ar egenvektorn till kovariansmatrisen, utskriven -- tva
    rader slaar att dra in ett bibliotek som QGIS anda inte har.
    """
    n = len(punkter)
    mx = sum(p.x for p in punkter) / n
    my = sum(p.y for p in punkter) / n
    sxx = sum((p.x - mx) ** 2 for p in punkter)
    syy = sum((p.y - my) ** 2 for p in punkter)
    sxy = sum((p.x - mx) * (p.y - my) for p in punkter)
    vinkel = 0.5 * math.atan2(2 * sxy, sxx - syy)      # mot x-axeln, oster
    barning = (90 - math.degrees(vinkel)) % 360        # mot norr
    return barning, axel(barning)


def mat(klunga: list[Punkt]) -> Matt:
    """Langd, huvudriktning, antal och inbordes avstand.

    Precis de fyra uppgifter beskrivningsprincipen borjar med: "Forst anges
    hela systemets langd och huvudriktning. Darefter anges antalet
    fangstgropar samt groparnas form och deras inbordes avstand."

    Langden mats langs huvudaxeln och inte som kedjans summa: det ar
    systemets utstrackning som avses.
    """
    barning, riktning = _huvudriktning(klunga)
    lutning = math.radians(90 - barning)
    langs = [p.x * math.cos(lutning) + p.y * math.sin(lutning) for p in klunga]
    avstand = [round(a.till(b)) for a, b in kanter(klunga)] or [0]
    utstrackning = max(langs) - min(langs)
    return Matt(
        antal=len(klunga),
        langd=round(utstrackning),
        riktning=riktning,
        minsta_avstand=min(avstand),
        storsta_avstand=max(avstand),
        utstrackning=utstrackning,
        barning=barning,
    )


def langdtext(matt: Matt) -> str:
    """Systemets langd som den skrivs: "ca 125 m l (huvudriktning N–S)".

    **Langden ar delarnas utstrackning, inte ytans.** Principen sager "forst
    anges hela systemets langd och huvudriktning", och begransningslinjen ar
    nagot som ritas *kring* groparna pa kartan. Hur brett den ritas sager
    kallan inte; marginalen ar ett arbetsmatt. Ett matt taget pa ytan blir
    darfor tva marginaler for langt -- 145 m dar groparna stracker sig 126.

    Bade utkastet och knappen Matt ur geometrin skriver med den har
    funktionen. Forr raknade de var for sig, pa var sin sak och med var sin
    avrundning, och gav olika langd for samma system.
    """
    return langdmatt(matt.utstrackning or matt.langd, matt.barning, True)


def avstandstext(matt: Matt) -> str:
    """Delarnas inbordes avstand: "30–43 m", eller "32 m" nar alla ar lika.

    Ett spann med samma tal i bada andar -- "32–32 m" -- ar inget spann.
    """
    if matt.minsta_avstand == matt.storsta_avstand:
        return f"{matt.minsta_avstand} m"
    return f"{matt.minsta_avstand}–{matt.storsta_avstand} m"


# Mattorden som falthandboken och exempelsamlingen anvander. Ordningen ar
# handbokens: langd, bredd, hojd/djup, och darefter det som beskrivs inifran
# och ut.
MATTORD = (
    ("l", "l"),
    ("diam", "diam"),
    ("br", "br"),
    ("dj", "dj"),
    ("h", "h"),
)

# Ett matt som falthandboken skriver det: "meter med en eller hogst tva
# decimaler: 1 m, 1,2 m eller 1,45 m", och ofta som ett spann: "2-5 m diam".
_MATT = re.compile(
    r"(\d+(?:,\d+)?)\s*(?:[-–]\s*(\d+(?:,\d+)?))?\s*m\s+"
    r"(diam|dj|br|h|l)\b"
)


@dataclass
class Mattspann:
    """Ett matt over flera lamningar: minsta, storsta, och hur manga det bygger pa."""

    ord: str
    minsta: float
    storsta: float
    antal: int

    def __str__(self) -> str:
        def tal(varde: float) -> str:
            text = f"{varde:.2f}".rstrip("0").rstrip(".")
            return text.replace(".", ",")

        if self.minsta == self.storsta:
            return f"{tal(self.minsta)} m {self.ord}"
        return f"{tal(self.minsta)}–{tal(self.storsta)} m {self.ord}"


def matt_ur_beskrivningar(texter) -> tuple[list[Mattspann], int]:
    """Slaar ihop groparnas egna matt till spann.

    Beskrivningsprincipen for systemet vill ha groparnas matt, och de staar
    redan skrivna -- i falt, en gaang per grop. Att skriva av nitton
    beskrivningar for hand for att hitta minsta och storsta diameter ar
    arbete en dator gor battre.

    **Bara det som gaar att lasa sakert.** Matten plockas ut i
    falthandbokens egen form -- tal i meter med hogst tva decimaler, foljt av
    mattordet -- och varje spann bar hur manga gropar det bygger pa.
    Stammer inte antalet med antalet gropar sa syns det, i stallet for att
    ett spann ur halva materialet ser ut att galla allt.

    Returnerar spannen och hur manga texter som gick att lasa nagot ur.
    """
    funna: dict[str, list[float]] = {}
    lasta = 0
    for text in texter:
        if not text:
            continue
        traffar = _MATT.findall(str(text))
        if traffar:
            lasta += 1
        for forsta, andra, ord_ in traffar:
            varden = funna.setdefault(ord_, [])
            varden.append(float(forsta.replace(",", ".")))
            if andra:
                varden.append(float(andra.replace(",", ".")))

    ordning = [ord_ for ord_, _ in MATTORD]
    spann = [
        Mattspann(
            ord=ord_,
            minsta=min(funna[ord_]),
            storsta=max(funna[ord_]),
            antal=len(funna[ord_]),
        )
        for ord_ in ordning
        if ord_ in funna
    ]
    return spann, lasta


def _ordet_for_delarna(punkter, regel: Regel) -> str:
    """Vad delarna ska heta i beskrivningen.

    Har alla samma typ heter de den; det ar fallet med fangstgropar. Ett
    gravfalt kan besta av tolv olika gravtyper, och da vore vilket som helst
    av dem fel att skriva ut.
    """
    typer = {punkt.typ for punkt in punkter if punkt.typ}
    if len(typer) == 1:
        return next(iter(typer)).lower() + "ar"
    if regel.enda_ingaende:
        return regel.enda_ingaende.lower() + "ar"
    return "lämningar"


def beskrivningsutkast(matt: Matt, regel: Regel, texter=None, punkter=None) -> str:
    """Beskrivningens matbara borjan, i listans egen ordning.

    Forsta stycket ar de fyra uppgifter beskrivningsprincipen borjar med.
    Andra stycket ar delarnas egna matt, sammanslagna -- de staar redan
    skrivna, en gaang per lamning, och att lasa av nitton beskrivningar for
    hand for att hitta minsta och storsta diameter ar arbete en dator gor
    battre.

    Allt som inte gaar att rakna staar inom hakparentes. Formen, bottenplanet
    och vad matten avser ar arkeologens, och en mening som ser fardig ut ar
    varre an en som syns vara halv -- den forra skrivs under, den senare
    fylls i.
    """
    # Delarnas namn i forsta stycket -- "19 fangstgropar". I hakparentesen
    # heter de "delarna": genitiv av tjugoen olika typnamn gaar inte att
    # boja saakert, och "fangstgropars" ar inte svenska.
    ordet = _ordet_for_delarna(punkter or [], regel)
    stycken = [
        f"{regel.sammansatt}, {langdtext(matt)}, bestående av {matt.antal}"
        f" {ordet}, med ett inbördes avstånd av {avstandstext(matt)}."
    ]

    spann, lasta = matt_ur_beskrivningar(texter or [])
    if spann:
        stycken.append(
            f"[Ur delarnas egna beskrivningar ({lasta} av {matt.antal}): "
            + ", ".join(str(varde) for varde in spann)
            + ". Formen, bottenplanet och vad måtten avser skrivs här.]"
        )
    else:
        stycken.append("[Formen och måtten fylls i här.]")
    return "\n\n".join(stycken)


def forslag(
    punkter: list[Punkt], regel: Regel, avstand: float | None = None
) -> Rapport:
    """Gaar igenom punkterna och lamnar det som gaar att rakna.

    Klungor med tillrackligt manga blir kandidater. De med for faa namns for
    sig -- de ar inte system, och det ar dar bedomningen behovs. Klungor som
    ligger nara varandra namns ocksa: kommentaren tillater att avstandet
    overstiger forvalet, sa narheten ar en fraaga och inget fel.
    """
    avstand = regel.normalt_avstand if avstand is None else avstand
    rapport = Rapport()
    alla = klungor(punkter, avstand)

    for klunga in alla:
        if len(klunga) >= regel.minsta_antal:
            rapport.kandidater.append(
                Kandidat(punkter=klunga, matt=mat(klunga), kanter=kanter(klunga))
            )
        else:
            rapport.for_faa.append(klunga)

    for i, en in enumerate(alla):
        for j, tva in enumerate(alla[i + 1:], start=i + 1):
            kortast = min(a.till(b) for a in en for b in tva)
            if kortast <= avstand * 3:
                rapport.narliggande.append((i, j, round(kortast)))

    return rapport
