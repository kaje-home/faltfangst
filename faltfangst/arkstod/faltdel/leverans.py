"""Leveranslistan: det jobbet gjort, i den ordning Fornreg fragar efter det.

Faltblanketten ar byggd efter hur man arbetar i falt, och ska forbli det. Det
ar utskriften som ska folja Fornregs ordning, inte inmatningen -- annars far
man ett samre faltformular for att slippa leta vid webbformularet.

Registreringen sker pa en kontorsdator dit arbetsmappen kopierats, och
Fornreg tar inte emot en GeoPackage. Man klistrar in falt for falt. Listan ar
darfor en HTML-fil i arbetsmappen: den foljer med kopieringen, oppnas i vilken
webblasare som helst utan QGIS eller Python, och star i ett fonster bredvid
Fornreg i det andra.

Kontrollerna star vid det falt de galler i stallet for i en egen lista. Det ar
skillnaden mot kvallsvyn, som var en separat korning man skulle komma ihaag --
har dyker "skadan ska beskrivas" upp i det ogonblick skadebeskrivningen ska
fyllas i.

Faltordningen ar Fornregs egen, ur handledningens innehallsforteckning.
"""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from arkstod.faltdel import utgangslage as utgangslagesmodul
from arkstod.faltdel.formular import QGIS_NULL
from arkstod.faltdel.motivering import vilar_bara_pa_arstalet
from arkstod.faltdel.kontroller import (
    granska_narhet,
    granska_beskrivning,
    granska_geometri,
    granska_geometripraxis,
    granska_matning,
    granska_status,
    geometripraxis,
    yta_utan_matt,
)

FILNAMN = "leveranslista.html"

# Geometrisorterna i den ordning man registrerar dem: punkter forst, sedan
# ytor, sist linjer.
GEOMETRIORDNING: tuple[tuple[str, str], ...] = (
    ("point", "Punkter"),
    ("polygon", "Ytor"),
    ("linestring", "Linjer"),
)


@dataclass(frozen=True)
class Falt:
    """Ett falt i Fornregs formular, och kolumnen det hamtas ur."""

    etikett: str
    kolumn: str
    # Falt som inte gaar till Fornreg visas anda -- de kan bara nagot man vill
    # ha framfor sig -- men aldrig bland dem man klistrar.
    levereras: bool = True


# Ordningen ar Fornregs, ur "Arbeta med lamningsinformation" 4.0.
#
# Tre av handledningens falt saknar kolumn i uttaget och star darfor inte har:
# Hojd over havet, Referenser och Kommentar till undersokningsstatus.
FORNREG_ORDNING: tuple[Falt, ...] = (
    Falt("Lämningstyp", "lamningstyp"),
    Falt("Beskrivning av lämning", "beskrivning"),
    Falt("Registreringsstatus", "aktualitetstatus"),
    Falt("Antikvarisk bedömning", "antikvariskbedomning"),
    Falt("Motivering till antikvarisk bedömning", "antikvariskbedomning_motivering"),
    Falt("Antikvarisk kommentar", "Kommentar"),
    Falt("Grad av skada", "skadestatus"),
    Falt("Skadebeskrivning", "Skadebesk"),
    Falt("Undersökningsstatus", "undersokningsstatus"),
    Falt("Orientering", "orientering"),
    Falt("Placering", "placering"),
    Falt("Datum för senaste fältbesök", "Granskningsdatum"),
    Falt("Terräng kring lämning", "terrang"),
    Falt("Vegetation på lämning", "veg"),
    Falt("Tradition", "tradition"),
    Falt("Namn på lämning", "lamningsnamn"),
    # Lagesuppgiftens kvalitet. Bada registreras i Fornreg under Lage och
    # utbredning, och bada ska alltid anges -- FMIS-handledningen s. 34.
    # De stod inte i listan forr, och da gick de inte heller att kontrollera:
    # en anmarkning pa ett falt som inte visas ar en anmarkning ingen ser.
    Falt("Mätmetod", "matmet"),
    Falt("Medelfel (± m)", "medelfel"),
    # Egen minnesanteckning. Fornreg har inget falt for den.
    Falt("Egen anteckning", "ovrigt", levereras=False),
)


@dataclass
class Anmarkning:
    """Nagot att titta pa, vid det falt det galler."""

    text: str
    ar_krav: bool = True


@dataclass
class Post:
    """En lamning att registrera."""

    tabell: str
    fid: int
    lamningsnummer: str
    lamningstyp: str
    tid: int | None
    ny: bool
    # RAA:s egen lank till lamningen i Fornsok. Uttaget bar den, och den ar
    # enda vagen till de uppgifter uttaget inte innehaller.
    lank: str = ""
    varden: dict[str, str] = field(default_factory=dict)
    anmarkningar: dict[str, list[Anmarkning]] = field(default_factory=dict)
    # De lamningar som ingaar i den har, om den ar sammansatt.
    delar: list["Delpost"] = field(default_factory=list)

    @property
    def sorteringsnyckel(self) -> tuple[int, int]:
        """TID stigande. Rader utan TID sist, i fid-ordning."""
        return (0, self.tid) if self.tid is not None else (1, self.fid)


@dataclass
class Delpost:
    """En lamning som blivit del av en sammansatt lamning.

    Den staar inte i listan -- systemet ar lamningen och den har ingen egen
    text att skriva in. Men geometrin hor till systemet och maste levereras,
    sa den behover folja med anda. `ingar_i` ar systemets lopnummer.
    """

    tabell: str
    fid: int
    lamningstyp: str
    tid: int | None
    ingar_i: int
    # Groparnas egen beskrivning, skriven i falt. Den ar ravaran nar
    # systemets matt ska slaas ihop, sa den maste synas dar systemets text
    # skrivs.
    beskrivning: str = ""


@dataclass
class Sammanrakning:
    """Vad jobbet gav, i tal. Det man vill kunna saga utan att rakna rader."""

    nya: int = 0
    reviderade: int = 0
    # tabell -> (nya, reviderade). Rubrikerna kommer ur GEOMETRIORDNING.
    per_geometri: dict[str, tuple[int, int]] = field(default_factory=dict)
    # lamningstyp -> (nya, reviderade), vanligast forst.
    per_typ: list[tuple[str, int, int]] = field(default_factory=list)
    # Rader som ar rorda men inte levereras for sig: de har blivit delar av
    # en sammansatt lamning. Utan talet ser listan ut att tappa lamningar.
    delar: int = 0

    @property
    def totalt(self) -> int:
        return self.nya + self.reviderade


@dataclass
class Leveransrapport:
    gpkg: Path
    uttagsdatum: str = ""
    poster: list[Post] = field(default_factory=list)
    # Lamningar som blivit delar av en sammansatt lamning. Inte i listan --
    # men deras geometrier ska levereras med systemet.
    delposter: list[Delpost] = field(default_factory=list)

    def per_geometri(self) -> list[tuple[str, list[Post]]]:
        ut = []
        for tabell, rubrik in GEOMETRIORDNING:
            valda = sorted(
                (post for post in self.poster if post.tabell == tabell),
                key=lambda post: post.sorteringsnyckel,
            )
            ut.append((rubrik, valda))
        return ut

    @property
    def antal(self) -> int:
        return len(self.poster)

    def sammanrakning(self) -> Sammanrakning:
        """Rakningen ur posterna. Inget eget urval -- samma lamningar."""
        rakning = Sammanrakning(delar=len(self.delposter))
        per_typ: dict[str, list[int]] = {}
        for tabell, _ in GEOMETRIORDNING:
            valda = [post for post in self.poster if post.tabell == tabell]
            if not valda:
                continue
            nya = sum(1 for post in valda if post.ny)
            rakning.per_geometri[tabell] = (nya, len(valda) - nya)
        for post in self.poster:
            rad = per_typ.setdefault(post.lamningstyp or "utan lämningstyp", [0, 0])
            rad[0 if post.ny else 1] += 1
            if post.ny:
                rakning.nya += 1
            else:
                rakning.reviderade += 1
        rakning.per_typ = sorted(
            ((typ, nya, rev) for typ, (nya, rev) in per_typ.items()),
            key=lambda rad: (-(rad[1] + rad[2]), rad[0]),
        )
        return rakning


def _motiveringskrav(anslutning: sqlite3.Connection) -> dict[str, tuple[bool, str]]:
    try:
        return {
            rad[0]: (bool(rad[1]), rad[2])
            for rad in anslutning.execute(
                "SELECT lamningstyp, kravs, besked FROM ark_motivering"
            ).fetchall()
        }
    except sqlite3.OperationalError:
        return {}


def _egen_skada(post: Post, fore: dict[str, str] | None) -> bool:
    """Om skadan ar jobbets egen uppgift, inte RAA:s arvda.

    Kravet "aatverkan kraver en beskrivning" hor till det man sjalv
    registrerar. RAA:s oppna uttag bar `skadestatus` men **ingen
    skadebeskrivning alls** -- den finns hos RAA och syns i Fornsok, den
    foljer bara inte med i nedladdningen.

    Foljden var att varje lamning RAA markt som skadad kom in i arbetsfilen
    med status men utan beskrivning, och anmarkningen slog till pa hela
    lanet. Den var dessutom osann: den sa att en uppgift saknades som inte
    saknar. Rapporterat fran falt pa L1945:6118, dar Fornsok har "En
    rotvalta, korspar."

    Ar lamningen ny, eller har jobbet andrat skadestatus, ar det jobbets
    egen uppgift och da galler kravet.
    """
    if post.ny or fore is None:
        return True
    return post.varden.get("skadestatus", "") != fore.get("skadestatus", "")


def _granska_lopnummer(rapport: "Leveransrapport") -> None:
    """Sager ifran om tva lamningar i samma lager bar samma TID.

    TID ar verktygets primarnyckel utan att nagon bestamt det: autotexten
    soker pa den, geometrizippen grupperar pa den, listan sorterar pa den,
    och ett sammansatt lamnings delar binds med den. `falt.py` sager
    "unikt och obligatoriskt" -- men ingenting har hallit efter det.

    En dubblett ar inget verktyget kan rata ut sjalvt: vilket av de tva som
    ska byta nummer ar en fraaga for den som registrerat. Darfor en
    anmarkning vid faltet, dar den syns nar man anda laser posten.
    """
    per_lager: dict[tuple[str, int], list[Post]] = {}
    for post in rapport.poster:
        if post.tid is not None:
            per_lager.setdefault((post.tabell, post.tid), []).append(post)

    for (_, tid), poster in per_lager.items():
        if len(poster) < 2:
            continue
        for post in poster:
            andra = [
                annan.lamningsnummer or f"fid {annan.fid}"
                for annan in poster
                if annan is not post
            ]
            post.anmarkningar.setdefault("TID", []).append(
                Anmarkning(
                    f"TID {tid} bärs också av {', '.join(andra)}. Löpnumret"
                    " ska vara unikt inom geometrilagret — det är på det"
                    " geometrierna knyts ihop i leveransen.",
                    ar_krav=True,
                )
            )


def _granska_post(
    post: Post,
    krav: dict[str, tuple[bool, str]],
    praxis: dict[str, dict[str, int]],
    geometri: bytes | None,
    fore: dict[str, str] | None = None,
) -> None:
    """Lagger anmarkningarna vid de falt de galler.

    Kontrollerna sjalva bor i `kontroller`. Har avgors bara var de hamnar --
    och det ar hela skillnaden mot kvallsvyn, som samlade dem i en lista man
    laste efterat.
    """
    rad = dict(post.varden, geometri=geometri, fid=post.fid)

    def lagg(kolumn: str, text: str, ar_krav: bool = True) -> None:
        post.anmarkningar.setdefault(kolumn, []).append(Anmarkning(text, ar_krav))

    beskrivning = post.varden.get("beskrivning", "")
    for anmarkning in granska_beskrivning(beskrivning):
        lagg("beskrivning", anmarkning.text, ar_krav=False)

    # Tre falt till bar matt och vaderstreck i lopande text, och darmed
    # samma formregler som beskrivningen:
    #
    #   orientering  en vaganvisning -- "15 m V om back", "20 m Ö om
    #                kraftledningsgata (NNÖ-SSV)"
    #   terrang      lamningens lage och markanvandning, i tva led --
    #                "Kammen av grusas (NV-SÖ). Skogsmark, barrskog."
    #   veg          vaxtligheten direkt pa lamningen -- "1 stor tall i
    #                gropens S del och 2 sma granar pa vallen"
    #
    # Parentesen i en terrangbeskrivning ar landformens egen langdriktning,
    # och axelregeln galler den lika val som beskrivningens.
    for falt in ("orientering", "terrang", "veg"):
        for anmarkning in granska_beskrivning(post.varden.get(falt, "")):
            lagg(falt, anmarkning.text, ar_krav=False)

    # Motiveringen: bade kravet och beskedet att kravet inte galler. Det andra
    # ar lika nyttigt -- det sager att man inte behover leta.
    kravs, besked = krav.get(post.lamningstyp, (False, ""))
    if besked:
        tom = not post.varden.get("antikvariskbedomning_motivering", "").strip()
        fornlamning = post.varden.get("antikvariskbedomning") == "Fornlämning"
        if kravs and fornlamning and tom:
            lagg("antikvariskbedomning_motivering", besked, ar_krav=True)
        elif not kravs:
            lagg("antikvariskbedomning_motivering", besked, ar_krav=False)

    # Och motiveringens innehall. Falthandboken s. 20: arstalet ensamt duger
    # inte som argument.
    if vilar_bara_pa_arstalet(
        post.varden.get("antikvariskbedomning_motivering", "")
    ):
        lagg(
            "antikvariskbedomning_motivering",
            "Motiveringen vilar bara på årtalet. Dateringen före 1850 ska "
            "aldrig vara det enda argumentet — skriv också vad i lämningens "
            "form, konstruktion, läge eller sammanhang som bär bedömningen.",
            ar_krav=False,
        )

    for anmarkning in granska_matning(post.tabell, rad, post.lamningstyp):
        lagg(
            {"mätmetod": "matmet"}.get(anmarkning.regel, "medelfel"),
            anmarkning.text,
        )

    # Statusreglerna, var och en vid sitt eget falt. `obekraftad` hoppas
    # over: att en uppgift inte ar bekraftad i falt ar ett faktum man just
    # registrerat, inte ett fel, och statusen star redan i listan.
    for anmarkning in granska_status(post.tabell, rad, post.lamningstyp):
        kolumn = {
            "status": "antikvariskbedomning",
            "skadebeskrivning": "Skadebesk",
            "registreringsstatus": "aktualitetstatus",
            "typens bedömning": "antikvariskbedomning",
            "tradition": "tradition",
            "överförd": "beskrivning",
        }.get(anmarkning.regel)
        if kolumn == "Skadebesk" and not _egen_skada(post, fore):
            # Skadan ar RAA:s, och beskrivningen finns -- i Fornsok, inte i
            # uttaget. Ett krav vore osant; ett besked om var den star ar
            # det man behover nar man reviderar en tidigare registrering.
            lagg(
                "Skadebesk",
                "Skadan kommer ur uttaget. RAÄ:s öppna uttag bär ingen "
                "skadebeskrivning — den står i Fornsök. Läs den där och "
                "klistra in den här om den ska följa med.",
                ar_krav=False,
            )
            continue
        if kolumn:
            lagg(kolumn, anmarkning.text)

    # Geometrin hor till lagesuppgiften, inte till beskrivningen -- men det
    # ar beskrivningens matt den provas mot, och det ar dar man ser den.
    for anmarkning in (
        granska_geometri(post.tabell, rad, beskrivning),
        yta_utan_matt(post.tabell, rad) if not beskrivning.strip() else None,
        granska_geometripraxis(post.tabell, rad, post.lamningstyp, praxis),
    ):
        if anmarkning is not None:
            lagg(
                "beskrivning",
                anmarkning.text,
                ar_krav=anmarkning.regel != "geometripraxis",
            )


def leverans(gpkg: Path | str) -> Leveransrapport:
    """Lamningarna som jobbet skapat eller reviderat, mot uttagets avtryck."""
    gpkg = Path(gpkg)
    if not gpkg.exists():
        raise FileNotFoundError(f"ingen GPKG pa {gpkg}")

    anslutning = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    try:
        rapport = Leveransrapport(gpkg=gpkg)
        try:
            rapport.uttagsdatum = (
                anslutning.execute(
                    "SELECT hamtdatum FROM ark_modell LIMIT 1"
                ).fetchone()
                or ("",)
            )[0]
        except sqlite3.OperationalError:
            pass

        if not utgangslagesmodul.finns(anslutning):
            raise SaknarUtgangslage(
                f"{gpkg.name} har inget avtryck av uttaget, så det går inte "
                "att se vad jobbet ändrat. Avtrycket skrivs när arbetsmappen "
                "skapas."
            )

        krav = _motiveringskrav(anslutning)
        praxis = geometripraxis(anslutning)
        geometrier: dict[tuple[str, int], bytes | None] = {}
        for tabell in utgangslagesmodul.geometritabeller(anslutning):
            fore = utgangslagesmodul.las_avtryck(anslutning, tabell)
            bevarade = utgangslagesmodul.las_bevarade(anslutning, tabell)
            nu = utgangslagesmodul.berakna(anslutning, tabell)
            andrade = [fid for fid, varde in nu.items() if fore.get(fid) != varde]
            if not andrade:
                continue

            kolumner = {
                rad[1]
                for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")')
            }
            valda = [
                falt.kolumn for falt in FORNREG_ORDNING if falt.kolumn in kolumner
            ]
            extra = [
                kolumn
                # publiceringsdatum staar inte pa blanketten och renderas
                # inte i listan, men regeln om nypatraffade forstorda
                # lamningar behover veta om lamningen nagonsin varit
                # publicerad. Se status.kraver_obekraftad.
                for kolumn in (
                    "lamningsnummer",
                    "raa_nummer",
                    "TID",
                    "url",
                    "publiceringsdatum",
                )
                if kolumn in kolumner
            ]
            geometrikolumn = ["geometri"] if "geometri" in kolumner else []
            citerade = ", ".join(
                f'"{k}"' for k in ["fid", *valda, *extra, *geometrikolumn]
            )
            anslutning.row_factory = sqlite3.Row
            platser = ", ".join("?" for _ in andrade)
            # En grop som blivit del av ett fangstgropssystem levereras inte
            # som en egen lamning. Systemet ar lamningen och groparna dess
            # delar -- Fornsok skriver det som "Lamningen bestar av:
            # Fangstgrop, antal 19". Se falt.py, kolumnen ingar_i.
            har_del = "ingar_i" in kolumner
            if har_del:
                citerade += ', "ingar_i"'
            for rad in anslutning.execute(
                f"SELECT {citerade} FROM \"{tabell}\" WHERE fid IN ({platser})",
                andrade,
            ):
                data = dict(rad)
                # En grop som blivit del av ett fangstgropssystem ar ingen
                # egen lamning: systemet ar lamningen och groparna dess
                # delar. Den ska darfor inte i listan -- men **geometrin ska
                # levereras**. Beskrivningsprincipen sager att varje grop
                # ritas in som en punkt och att groparna darefter binds ihop
                # med en omgivande begransningslinje, sa systemets geometri
                # ar punkterna *och* ytan. Se fornreg.py.
                if data.get("ingar_i"):
                    rapport.delposter.append(
                        Delpost(
                            tabell=tabell,
                            fid=data["fid"],
                            lamningstyp=data.get("lamningstyp") or "",
                            tid=data.get("TID"),
                            ingar_i=int(data["ingar_i"]),
                            beskrivning=data.get("beskrivning") or "",
                        )
                    )
                    continue
                post = Post(
                    tabell=tabell,
                    fid=data["fid"],
                    lamningsnummer=(
                        data.get("lamningsnummer") or data.get("raa_nummer") or ""
                    ),
                    lamningstyp=data.get("lamningstyp") or "",
                    tid=data.get("TID"),
                    ny=data["fid"] not in fore,
                    lank=data.get("url") or "",
                    varden={
                        kolumn: "" if data.get(kolumn) is None else str(data[kolumn])
                        for kolumn in valda
                    },
                )
                _granska_post(
                    post,
                    krav,
                    praxis,
                    data.get("geometri"),
                    bevarade.get(data["fid"]),
                )
                # Geometrin behovs efterat, for narhetskontrollen. Den
                # kan inte goras har: den fragar om andra nya lamningar, och
                # de ar inte kanda forran alla lager gaatts igenom.
                geometrier[(tabell, data["fid"])] = data.get("geometri")
                rapport.poster.append(post)

        # Ligger nagon ny lamning ovanpa en som redan ar registrerad?
        # Fragan galler bara de egna nyregistreringarna, och de maste vara
        # kanda allihop innan den stalls -- annars pekar tva nya lamningar
        # bredvid varandra ut varandra.
        egna = {post.fid for post in rapport.poster if post.ny}
        for post in rapport.poster:
            if not post.ny:
                continue
            narhet = granska_narhet(
                anslutning,
                post.tabell,
                post.fid,
                post.lamningstyp,
                geometrier.get((post.tabell, post.fid)),
                egna,
            )
            if narhet is not None:
                # Inget krav: att tva lamningar ligger nara varandra ar en
                # fraaga, inte ett fel. Det kan mycket val vara tva gropar.
                post.anmarkningar.setdefault("lamningstyp", []).append(
                    Anmarkning(narhet.text, ar_krav=False)
                )

        _granska_lopnummer(rapport)

        # Delarna hangs pa sitt system. Groparnas texter behovs dar systemets
        # text skrivs -- det ar ur dem matten slaas ihop.
        for del_ in rapport.delposter:
            for post in rapport.poster:
                if post.tid == del_.ingar_i:
                    post.delar.append(del_)
                    break
        return rapport
    finally:
        anslutning.close()


class SaknarUtgangslage(Exception):
    """Arbetsfilen bar inget avtryck att jamfora mot."""


def _rutan(falt: Falt, varde: str, val: list[str] | None) -> str:
    """Vardet som en ruta man kan skriva i, eller en lista man valjer ur.

    Rullistefalten far en lista i stallet for fri text: ett statusvarde
    utanfor listan slaar sonder statusreglerna, och det ska inte gaa att
    skriva av misstag mitt i en leverans.

    `data-ursprung` bar vardet som stod i arbetsfilen nar listan skrevs. Det
    ar bade facit for vad som andrats och det `fran` som rattelsen provas mot
    innan den skrivs in.
    """
    gemensamt = (
        f' data-kolumn="{falt.kolumn}"'
        f' data-ursprung="{html.escape(varde, quote=True)}"'
    )
    if val is None:
        # contenteditable, inte <textarea>: rutan ska vaxa med texten och se
        # ut som texten den ar, inte som ett formularfalt.
        return (
            f'<div class="varde"{gemensamt} contenteditable="true"'
            ' spellcheck="false">'
            f"{html.escape(varde)}</div>"
        )

    rader = ['<option value=""></option>']
    for ett in val:
        # QGIS platshaallare for "inget varde" ar inget val. Listorna rensas
        # redan dar de lases; har halls den ute aven om nagon skickar in den.
        if ett == QGIS_NULL:
            continue
        vald = " selected" if ett == varde else ""
        rader.append(f'<option{vald}>{html.escape(ett)}</option>')
    if varde and varde not in val:
        # Ett varde som inte langre finns i listan ska synas, inte tyst
        # bytas mot tomt nar rutan ritas.
        rader.append(
            f'<option selected>{html.escape(varde)}</option>'
        )
    return f'<select class="varde valj"{gemensamt}>' + "".join(rader) + "</select>"


def _falt_html(post: Post, falt: Falt, listor: dict[str, list[str]]) -> str:
    varde = post.varden.get(falt.kolumn, "")
    anmarkningar = post.anmarkningar.get(falt.kolumn, [])
    if not varde and not anmarkningar:
        return ""

    if not falt.levereras:
        return (
            '<div class="falt"><div class="privat"><b>'
            f"{html.escape(falt.etikett)}</b> — går inte till Fornreg: "
            f"<i>{html.escape(varde)}</i></div></div>"
        )

    delar = [
        '<div class="falt">',
        f'<div class="namn">{html.escape(falt.etikett)}</div>',
        _rutan(falt, varde, listor.get(falt.kolumn)),
        '<button type="button" onclick="kopiera(this)">Kopiera</button>',
        '<div class="fore"></div>',
    ]
    for anmarkning in anmarkningar:
        stil = "anm" if anmarkning.ar_krav else "anm mjuk"
        delar.append(f'<div class="{stil}">{html.escape(anmarkning.text)}</div>')
    delar.append("</div>")
    return "".join(delar)


def _fornsokslank(post: Post) -> str:
    """Lanken till lamningen i Fornsok.

    Uttaget bar 22 falt, och en del av det Fornsok visar ar inte med -- mest
    markbart skadebeskrivningen. Reviderar man en tidigare registrering
    behover man se vad som stod, och da ar lanken den enda vagen dit.
    """
    if not post.lank:
        return ""
    return (
        f'<a class="fornsok" href="{html.escape(post.lank, quote=True)}"'
        ' target="_blank" rel="noopener">Fornsök ↗</a>'
    )


def _delar_html(post: Post) -> str:
    """Ingaende lamningars egna beskrivningar, under systemets post.

    Groparna skrivs i falt, en text per grop, och de ar ravaran nar systemets
    matt ska slaas ihop -- minsta och storsta diameter kommer darifran. De
    levereras inte som egna lamningar, men de far inte gommas undan: det ar
    har systemets text skrivs.
    """
    if not post.delar:
        return ""
    rader = "".join(
        f"<li><b>TID {del_.tid}</b> {html.escape(del_.beskrivning or '—')}</li>"
        for del_ in sorted(
            post.delar, key=lambda d: (d.tid is None, d.tid or 0, d.fid)
        )
    )
    return (
        '<details class="delar">'
        f"<summary>{len(post.delar)} ingående lämningar — deras egna "
        "beskrivningar, att slå ihop måtten ur</summary>"
        f"<ul>{rader}</ul>"
        "</details>"
    )


def _post_html(post: Post, listor: dict[str, list[str]]) -> str:
    marke = "ny registrering" if post.ny else "reviderad"
    tid = f"TID {post.tid} · " if post.tid is not None else ""
    falt = "".join(_falt_html(post, f, listor) for f in FORNREG_ORDNING)
    nyckel = html.escape(f"{post.tabell}:{post.fid}")
    return (
        f'<article data-nyckel="{nyckel}" data-tabell="{html.escape(post.tabell)}"'
        f' data-fid="{post.fid}">'
        '<div class="topp">'
        '<input type="checkbox" onchange="vaxla(this)">'
        f'<span class="nr">{html.escape(post.lamningsnummer or "—")}</span>'
        f'<span class="typ">{html.escape(post.lamningstyp)}</span>'
        f'<span class="tid">{html.escape(tid + marke)}</span>'
        f"{_fornsokslank(post)}"
        "</div>"
        f"{falt}{_delar_html(post)}</article>"
    )


def _sammanrakning_html(rapport: Leveransrapport) -> str:
    """Rakningen som ett stycke overst: nytt, reviderat, per sort.

    Den svarar pa fragan man staller nar dagen ar slut och nagon vill veta
    vad som gjordes -- utan att man raknar rader i listan.
    """
    rakning = rapport.sammanrakning()
    if not rakning.totalt and not rakning.delar:
        return ""

    rubriker = dict(GEOMETRIORDNING)

    def sort(nya: int, reviderade: int) -> str:
        delar = []
        if nya:
            delar.append(f"{nya} ny{'a' if nya > 1 else ''}")
        if reviderade:
            delar.append(f"{reviderade} reviderad{'e' if reviderade > 1 else ''}")
        return ", ".join(delar)

    rader = [
        '<div class="rakning-detalj">',
        f"<b>{rakning.nya}</b> nyregistrerade · "
        f"<b>{rakning.reviderade}</b> reviderade",
    ]

    geometri = " · ".join(
        f"{html.escape(rubriker.get(tabell, tabell))} {nya + rev}"
        f" ({sort(nya, rev)})"
        for tabell, (nya, rev) in rakning.per_geometri.items()
    )
    if geometri:
        rader.append(f"<div>{geometri}</div>")

    typer = " · ".join(
        f"{html.escape(typ)} {nya + rev}" + (f" ({sort(nya, rev)})" if nya and rev else "")
        for typ, nya, rev in rakning.per_typ
    )
    if typer:
        rader.append(f"<div>{typer}</div>")

    if rakning.delar:
        rader.append(
            f"<div>{rakning.delar} lämningar ingår i en sammansatt lämning."
            " De har ingen egen text att skriva in — systemet är lämningen —"
            " men deras geometrier följer med systemet i zippen.</div>"
        )

    rader.append("</div>")
    return "\n".join(rader)


def html_sida(
    rapport: Leveransrapport,
    jobbnamn: str = "",
    listor: dict[str, list[str]] | None = None,
) -> str:
    """Leveranslistan som en fristaende HTML-fil."""
    listor = {} if listor is None else listor
    namn = jobbnamn or rapport.gpkg.parent.name
    avsnitt = []
    for rubrik, poster in rapport.per_geometri():
        avsnitt.append(f"<h2>{html.escape(rubrik)} — TID-ordning</h2>")
        if not poster:
            avsnitt.append(
                '<article><div class="topp"><span class="typ">Inga '
                f"{rubrik.lower()} i den här leveransen.</span></div></article>"
            )
            continue
        avsnitt.extend(_post_html(post, listor) for post in poster)

    return _mall().format(
        namn=html.escape(namn),
        antal=rapport.antal,
        sammanrakning=_sammanrakning_html(rapport),
        uttagsdatum=html.escape(rapport.uttagsdatum or "okänt"),
        skapad=date.today().isoformat(),
        nyckel=html.escape(f"leverans:{namn}"),
        avsnitt="\n".join(avsnitt),
    )


def skriv(gpkg: Path | str, jobbnamn: str = "") -> Path:
    """Skriver leveranslistan bredvid arbetsfilen och returnerar sokvagen."""
    from arkstod.faltdel.rattelse import _listor

    gpkg = Path(gpkg)
    rapport = leverans(gpkg)
    mal = gpkg.parent / FILNAMN
    # Rullistornas varden laeses ur projektet i samma mapp. Sidan ska inte
    # kunna erbjuda ett statusvarde formularet inte har.
    mal.write_text(
        html_sida(rapport, jobbnamn, _listor(gpkg)), encoding="utf-8"
    )
    return mal


# Sidans mall ligger i en egen fil. Den ar 395 rader HTML, CSS och
# JavaScript, och som strang i en pythonmodul gick den varken att formatera
# eller granska med verktyg som forstar den. `{}` ar formatplatser -- CSS:ens
# klamrar staar darfor dubblade i filen.
MALLFIL = Path(__file__).with_name("leveranslista.html")


def _mall() -> str:
    return MALLFIL.read_text(encoding="utf-8")
