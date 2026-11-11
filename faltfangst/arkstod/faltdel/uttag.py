"""Hela vagen fran RAA:s nedladdning till en arbetsfil man kan oppna.

Ett uttag hor till ett arbete, inte till en sasong. Det kan galla en enskild
utredning eller racka hela aret, och nasta arbete far ett eget uttag i en egen
mapp. Det ar billigt: nedladdningen tar minuter, och RAA:s data ar fardig.

Det har flodet byggdes forst tvartom -- ett uttag som ersatte det forra i
samma mapp, med en sammanfogning som bar over egna anteckningar och en
sakerhetskopia av den gamla filen. Konstruktionen loste ett problem som inte
finns nar mappen ar ny varje gaang, och den bar en risk som ar verklig: den
skrev i en fil nagon annan redan arbetat i.

Nu ror ett uttag aldrig en befintlig uppsattning. Finns det redan en arbetsfil
i mappen avbryts korningen och sager det. Faltdata som annu inte natt Fornreg
ligger kvar dar den skrevs -- den ar inte forlorad, den ar kvar i sitt eget
arbete.

Ordningen ar inte godtycklig: uppslagstabellerna skrivs in i arbetsfilen
(`skriv_till_gpkg`) efter migreringen, eftersom de ska bara forekomsttal ur
den fardiga datan.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from arkstod import lan as lansmodul
from arkstod.faltdel.mall import (
    ARBETSFIL,
    malfiler,
    namnge_efter_lan,
    sakerstall_mall,
    saknade_blanketter,
    saknade_lager,
    skriv_in_uppslagen,
)
from arkstod.faltdel.grannlan import Fogningsrapport, foga_in
from arkstod.faltdel.migrera import migrera
from arkstod.faltdel.projekt import satt_utsnitt
from arkstod.faltdel.uppslagsbok import skriv as skriv_uppslagsbok
from arkstod.faltdel.rutstorlek import anpassa as anpassa_rutor
from arkstod.faltdel.formular import satt_autotext, satt_typlista
from arkstod.faltdel import utgangslage as utgangslagesmodul
from arkstod.lamningstyper.gpkg import Exportrapport, skriv_till_gpkg
from arkstod.tolkning.skikt import Skikt


class ArbetsmappUpptagen(Exception):
    """Mappen har redan ett uttag, och ett nytt skulle skriva over arbete."""


# Windows langsta sokvag, med avslutande nolla. QGIS och Utforskaren haller
# sig till den, vad Python an klarar. Den galler aven dar mappen skapas pa
# annat system: arbetsmappen kopieras till faltdatorn och kontorsdatorn.
LANGSTA_SOKVAG = 259


def _for_lang_sokvag(
    arbetsmapp: Path, lanen: list[str], datum: str, lagg_ut_mall: bool
) -> str | None:
    """Den langsta sokvag uttaget kommer att skriva, om den ar for lang.

    Provas innan nagot hamtas. Forr fell det i sista steget, nar filerna
    doptes efter lanet -- da laa arbetsfilen redan i mappen, och mappen
    raknades som upptagen. Tva lan i namnet gor namnen langre, och en mapp
    djupt i Dokument racker da for att hamna dar.
    """
    namn = [
        lansmodul.gpkg_namn(lanen, datum),
        f"{lansmodul.mappnamn(lanen, datum)}.qgz",
        f"{ARBETSFIL}.granne{len(lanen)}.ny",
    ]
    if lagg_ut_mall:
        namn.extend(fil.name for fil in malfiler())
    langsta = max((str(arbetsmapp.absolute() / n) for n in namn), key=len)
    return langsta if len(langsta) > LANGSTA_SOKVAG else None


@dataclass
class Uttagsrapport:
    lan: str
    arbetsfil: Path
    # Lanen utover det forsta, nar arbetet gaar over lansgransen.
    grannlan: list[str] = field(default_factory=list)
    # Per grannlan: vad det tillforde och hur manga lamningar som redan fanns.
    fogning: dict[str, Fogningsrapport] = field(default_factory=dict)
    hamtade_byte: int = 0
    migrerade: dict[str, int] = field(default_factory=dict)
    utlagd_mall: list[str] = field(default_factory=list)
    avtryckta_lamningar: int = 0
    inskrivna_uppslag: list[str] = field(default_factory=list)
    saknade_lager: dict[str, list[str]] = field(default_factory=dict)
    saknade_blanketter: dict[str, list[str]] = field(default_factory=dict)
    # Kartans utsnitt nar projektet oppnas: (xmin, ymin, xmax, ymax), eller
    # None om arbetsfilen inte sager var lamningarna ligger.
    utsnitt: tuple[float, float, float, float] | None = None
    uppslagsbok: Path | None = None
    rutstorlekar: list[str] = field(default_factory=list)
    typlista: int = 0
    autotext: list[str] = field(default_factory=list)
    projektfil: Path | None = None
    export: Exportrapport | None = None


def foreslagen_mapp(
    lansnamn: str,
    forald: Path | str,
    datum: str | None = None,
    grannlan: tuple[str, ...] | list[str] = (),
) -> Path:
    """En ledig arbetsmapp med lanets namn och dagens datum.

    Namnet foljer den gamla uppsattningens egen konvention -- "Lamningsdatabas
    Jamtland 20260424" -- och datumet ar den dag uttaget gors. Nagot annat
    datum finns inte att ta: RAA:s lank pekar alltid pa det aktuella lanet och
    bar ingen egen stampel.

    Namnet ar ett forslag, inte ett tvang. Ett uttag hor till ett arbete, och
    ar arbetet namngivet ar det namnet battre. Men mappen maste vara ny varje
    gaang, och da ar lan plus datum ett battre utgangslage an den forra
    mappen -- som per definition redan ar upptagen.

    Tva uttag samma dag ar inte konstigt. Ar namnet taget raknas det upp.

    Med grannlan bar namnet bada: "Lamningsdatabas Jamtland och
    Vasternorrland 20260924".
    """
    forald = Path(forald)
    stam = lansmodul.mappnamn(
        [lansnamn, *grannlan], datum or date.today().strftime("%Y%m%d")
    )
    mapp = forald / stam
    nummer = 2
    while (mapp / ARBETSFIL).exists():
        mapp = forald / f"{stam} ({nummer})"
        nummer += 1
    return mapp


def _hamta(lansnamn: str, mal: Path, aterkoppling=None) -> int:
    adress = lansmodul.url(lansnamn)

    def rapportera(block, blockstorlek, total):
        if aterkoppling and total > 0:
            aterkoppling(min(block * blockstorlek, total), total)

    urllib.request.urlretrieve(adress, mal, reporthook=rapportera)
    return mal.stat().st_size


def nytt_uttag(
    lansnamn: str,
    arbetsmapp: Path | str,
    lamningstypsdatabas: Path | str,
    tolkning: list[Skikt] | None = None,
    aterkoppling=None,
    lagg_ut_mall: bool = True,
    grannlan: tuple[str, ...] | list[str] = (),
    meddela=None,
) -> Uttagsrapport:
    """Hamtar, bygger ut och skriver in uppslagen i en ny arbetsmapp.

    Arbetsfilen heter alltid `lamningar.gpkg` och ligger i `arbetsmapp`.
    Mappen ska vara ny eller tom pa uttag: ett nytt arbete far ett eget uttag,
    och verktyget skriver aldrig over en uppsattning nagon redan arbetat i.

    `grannlan` ar lan vars lamningar ska med i samma arbetsfil, nar arbetet
    gaar over lansgransen. De hamtas efter det forsta och fogas in fore
    migreringen; se `grannlan.py`. `meddela` far en rad text fore varje
    nedladdning, sa att den som vantar ser vilket lan det galler.
    """
    for namn in (lansnamn, *grannlan):
        if not lansmodul.ar_lan(namn):
            raise ValueError(f"okänt län: {namn}")
    lanen = lansmodul.lista([lansnamn, *grannlan])

    arbetsmapp = Path(arbetsmapp)
    arbetsfil = arbetsmapp / ARBETSFIL
    # Arbetsfilen bar lanets namn och datum nar uttaget ar klart, sa det
    # racker inte att leta efter det konstanta namnet -- da hade ett andra
    # uttag skrivit rakt in i det forsta.
    if arbetsfil.exists() or any(arbetsmapp.glob("*.gpkg")):
        raise ArbetsmappUpptagen(
            f"{arbetsmapp} har redan ett uttag. Ett nytt arbete får en egen "
            "mapp — det som redan är registrerat här ligger kvar där det "
            "skrevs."
        )

    datum = date.today().strftime("%Y%m%d")
    for_lang = _for_lang_sokvag(arbetsmapp, lanen, datum, lagg_ut_mall)
    if for_lang:
        raise ValueError(
            f"Sökvägen blir {len(for_lang)} tecken, och Windows klarar"
            f" {LANGSTA_SOKVAG}. Välj en mapp närmare roten, eller ett"
            f" kortare mappnamn: {for_lang}"
        )

    arbetsmapp.mkdir(parents=True, exist_ok=True)
    ny = arbetsfil.with_name(arbetsfil.name + ".ny")
    if ny.exists():
        ny.unlink()

    rapport = Uttagsrapport(
        lan=lanen[0], arbetsfil=arbetsfil, grannlan=lanen[1:]
    )
    if meddela:
        meddela(f"Hämtar {lansmodul.benamning(lanen[0])} från Riksantikvarieämbetet …")
    rapport.hamtade_byte = _hamta(lansnamn, ny, aterkoppling)

    # Grannlanen fogas in i RAA:s egen form, fore migreringen. Efter det ar
    # det en fil, och resten av uttaget behover inte veta att den var tva.
    for nummer, granne in enumerate(rapport.grannlan, start=1):
        if meddela:
            meddela(f"Hämtar {lansmodul.benamning(granne)} från Riksantikvarieämbetet …")
        tillfallig = arbetsmapp / f"{ARBETSFIL}.granne{nummer}.ny"
        try:
            rapport.hamtade_byte += _hamta(granne, tillfallig, aterkoppling)
            rapport.fogning[granne] = foga_in(ny, tillfallig)
        finally:
            if tillfallig.exists():
                tillfallig.unlink()

    migrering = migrera(ny)
    rapport.migrerade = dict(migrering.tabeller)
    rapport.export = skriv_till_gpkg(lamningstypsdatabas, ny, tolkning, lanen)

    # Avtrycket tas medan filen ar orord av manniskohand. Det ar mot det
    # leveranslistan senare jamfor for att veta vad jobbet andrat.
    rapport.avtryckta_lamningar = utgangslagesmodul.skriv(ny).antal

    # Filen tas i bruk forst nar allt annat lyckats. Ett avbrott mitt i lamnar
    # en `.ny` bakom sig och ingen halvfardig arbetsfil.
    ny.rename(arbetsfil)

    # Mallen sist: forst nar arbetsfilen finns ar projektet meningsfullt att
    # oppna.
    if lagg_ut_mall:
        rapport.utlagd_mall = sakerstall_mall(arbetsmapp)
        # Uppslagsmaterialet -- falthandbokens formregler -- skrivs in i
        # formularet som statisk text.
        rapport.inskrivna_uppslag = skriv_in_uppslagen(arbetsmapp, arbetsfil)
        # Projektet och arbetsfilen ska stamma. Gor de inte det moter
        # inventeraren en modal dialog i QGIS i stallet for en karta.
        rapport.saknade_lager = saknade_lager(arbetsmapp, arbetsfil)

        # Textrutornas hojd raknas ur lanets egen text. Sist av allt som ror
        # formularet: uppslagen skrivs in som text, storlekarna satts i XML,
        # och den ordningen ar den som halls.
        for formular in arbetsmapp.glob("*.ui"):
            rapport.rutstorlekar = anpassa_rutor(formular, arbetsfil).satta

        # Rullistan skrivs i lanets egen vanlighetsordning. Se
        # formular.satt_typlista for varfor den maste skrivas i projektet i
        # stallet for att slaas upp.
        for projekt in arbetsmapp.glob("*.qgz"):
            rapport.typlista = satt_typlista(projekt, arbetsfil)
            # Beskrivningen aterar forra lamningens text vid nyregistrering.
            # Tjugo kolbottnar pa rad skiljer sig bara i matten.
            rapport.autotext = satt_autotext(projekt)

        # Sist av allt: filerna far lanets namn och uttagets datum, som
        # mappen redan har. Efter det stammer inte langre `ARBETSFIL`.
        arbetsfil, projektfiler = namnge_efter_lan(
            arbetsmapp, arbetsfil, lanen, datum
        )
        rapport.arbetsfil = arbetsfil
        rapport.projektfil = next(iter(projektfiler.values()), None)
        rapport.utlagd_mall = sorted(
            fil.name for fil in arbetsmapp.iterdir() if fil.suffix in (".qgz", ".ui")
        )
        # Kartan ska oppna over det eller de lan uttaget galler -- inte
        # over rutan mallprojektet rakade vara sparat i.
        if rapport.projektfil is not None:
            rapport.utsnitt = satt_utsnitt(rapport.projektfil, arbetsfil)

        # Sist, nar projektet har sitt slutliga namn: pekar det pa en
        # blankett som inte finns oppnas ingenting nar man klickar pa en
        # lamning, och det marks forst i falt.
        rapport.saknade_blanketter = saknade_blanketter(arbetsmapp)

    # Uppslagsboken skrivs alltid, ocksa utan mall: den behover varken QGIS
    # eller projektet, och ska finnas i mappen fran forsta dagen i stallet
    # for nar nagon kommer pa att be om den.
    rapport.uppslagsbok = skriv_uppslagsbok(arbetsfil)
    return rapport
