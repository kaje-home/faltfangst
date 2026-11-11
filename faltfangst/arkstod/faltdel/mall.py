"""Faltuppsattningens mallfiler -- projekt och formular -- som filer i git.

Forra omgangen bakade in projektet, formularet och stilarna som base64 i
migreringsskriptet, och skrev om faltkonfigurationen ur dem vid varje uttag.
Det ar darfor varje anpassning forsvann: koden agde inte bara processen utan
ocksa produkten.

Har ar de vanliga filer. Uttaget kopierar dem om de saknas och ror dem annars
inte. Ingen genererar dem, ingen skriver om dem.

Det som gjorde omskrivningen nodvandig var att GPKG:ns filnamn bar datumet.
Nu heter den `lamningar.gpkg` i alla lan och vid varje uttag, och datumet star
i stallet i `ark_modell` inuti filen -- som modellversionen redan gor. En
arbetsdatabas som uppdateras pa plats har ingen stabil version att namnge;
dess tillstand ar "senaste uttag", och det hor hemma inuti.

Projektet daremot ar en levererad artefakt och bar sin version i namnet.
"""

from __future__ import annotations

import shutil
import zipfile
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape

from arkstod.faltdel.formular import FORMREGELMARKOR

PROJEKTROT = Path(__file__).resolve().parent.parent.parent
MALLMAPP = PROJEKTROT / "faltdel" / "mall"

# Arbetsfilens namn. Konstant med flit -- se modulens forklaring.
ARBETSFIL = "lamningar.gpkg"


def ar_faltuppsattning(mapp: Path | str) -> bool:
    """Ligger en faltfangstuppsattnings arbetsfil i mappen?

    Bada namnen raknas. Under bygget heter filen `lamningar.gpkg`; sist av allt
    ger `namnge_efter_lan` den lanets namn och uttagets datum, och efter det
    heter den `lamningar_lan_<lan>_<datum>.gpkg`. Den som provar mot enbart
    ARBETSFIL far aldrig traff pa en fardig uppsattning -- det var precis det
    felet kroken i pluginen gjorde i sin forsta version.
    """
    mapp = Path(mapp)
    if (mapp / ARBETSFIL).exists():
        return True
    return any(mapp.glob("l[aä]mningar*.gpkg"))


def malfiler(mapp: Path | str = MALLMAPP) -> list[Path]:
    """Mallens filer, i filnamnsordning."""
    return sorted(fil for fil in Path(mapp).iterdir() if fil.is_file())


def sakerstall_mall(
    arbetsmapp: Path | str, mapp: Path | str = MALLMAPP
) -> list[str]:
    """Lagger ut de mallfiler som saknas. Ror aldrig en fil som redan finns.

    Att skriva over en befintlig fil vore att gora om skriptets misstag: den
    som andrat nagot i sitt projekt ska inte fa det overskrivet av ett uttag.
    """
    arbetsmapp = Path(arbetsmapp)
    arbetsmapp.mkdir(parents=True, exist_ok=True)
    utlagda: list[str] = []
    for fil in malfiler(mapp):
        mal = arbetsmapp / fil.name
        if mal.exists():
            continue
        shutil.copy2(fil, mal)
        utlagda.append(fil.name)
    return utlagda


def _formregeltext(gpkg: Path) -> str:
    """Falthandbokens allmanna formregler, som HTML for formularets flik."""
    anslutning = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    try:
        rader = anslutning.execute(
            "SELECT rubrik, text FROM ark_formregel ORDER BY ordning"
        ).fetchall()
    except sqlite3.OperationalError:
        return ""
    finally:
        anslutning.close()

    if not rader:
        return ""
    return "".join(f"<p><b>{rubrik}</b><br/>{text}</p>" for rubrik, text in rader)



def skriv_in_uppslagen(arbetsmapp: Path | str, gpkg: Path | str) -> list[str]:
    """Byter formularets markorer mot uppslagsmaterialet.

    Falthandbokens formregler ar desamma for varje lamning. De hor darfor
    inte hemma som ett falt per rad -- och ett uttrycksfalt utan beroenden
    raknas aldrig om, sa fliken stod tom vid nyregistrering och fylldes forst
    nar lamningen sparats. Har skrivs de in en gaang, nar mallen laggs ut.

    Returnerar vilka markorer som faktiskt byttes.
    """
    arbetsmapp = Path(arbetsmapp)
    gpkg = Path(gpkg)
    # HTML:en ar text i ett XML-element, inte markup. Skrivs den oescapad blir
    # filen fortfarande giltig XML -- taggarna blir barnelement i stallet for
    # text -- och Qt laser strangen som tom. Formularet laddas da inte alls.
    ersattningar = {FORMREGELMARKOR: escape(_formregeltext(gpkg))}

    bytta: set[str] = set()
    for formular in arbetsmapp.glob("*.ui"):
        innehall = formular.read_text(encoding="utf-8")
        ny = innehall
        for markor, text in ersattningar.items():
            if not text or markor not in ny:
                continue
            ny = ny.replace(markor, text)
            bytta.add(markor)
        if ny != innehall:
            formular.write_text(ny, encoding="utf-8")
    return sorted(bytta)



def saknade_lager(arbetsmapp: Path | str, gpkg: Path | str) -> dict[str, list[str]]:
    """Lager projektet namner men som inte finns i arbetsfilen.

    Projektet och GPKG:n skrivs av samma korning och ska darfor stamma. De
    kan anda glida isar: ett projekt fran en nyare version som hamnar bredvid
    en aldre arbetsfil namner tabeller som inte finns dar.

    Felet visar sig som en modal dialog i QGIS -- "Handle Unavailable Layers"
    -- som last hela granssnittet innan man ens sett kartan. Det ar samma
    slags fel som en tabell utan rad i gpkg_contents: filen ser hel ut, och
    det som ar trasigt syns forst nar nagon oppnar den.

    Returnerar saknade lager per projektfil. Tom ordbok betyder att allt
    stammer.
    """
    import re
    import zipfile

    arbetsmapp, gpkg = Path(arbetsmapp), Path(gpkg)
    anslutning = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    try:
        finns = {
            rad[0]
            for rad in anslutning.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        anslutning.close()

    saknas: dict[str, list[str]] = {}
    for projekt in sorted(arbetsmapp.glob("*.qgz")):
        with zipfile.ZipFile(projekt) as arkiv:
            namn = [n for n in arkiv.namelist() if n.lower().endswith(".qgs")]
            if not namn:
                continue
            xml = arkiv.read(namn[0]).decode("utf-8")
        namngivna = set(re.findall(r"<layername>(ark_\w+)</layername>", xml))
        brist = sorted(namngivna - finns)
        if brist:
            saknas[projekt.name] = brist
    return saknas


def saknade_blanketter(arbetsmapp: Path | str) -> dict[str, list[str]]:
    """Blanketter projektet pekar pa men som inte finns i mappen.

    Utan filen oppnar QGIS ingen blankett alls nar man klickar pa en
    lamning -- inget felmeddelande, ingenting. Det hande med 1.4.6: pluginen
    packades upp med ett verktyg som laste a, a och o fel, och blanketten
    kopierades till mappen som `F+nltf+Nngstformul+nr 3.4.ui`. Projektet
    letade efter det ratta namnet, och felet syntes forst i falt.

    Returnerar saknade blankettfiler per projektfil. Tom ordbok betyder att
    allt stammer.
    """
    import html
    import re
    import zipfile

    arbetsmapp = Path(arbetsmapp)
    saknas: dict[str, list[str]] = {}
    for projekt in sorted(arbetsmapp.glob("*.qgz")):
        with zipfile.ZipFile(projekt) as arkiv:
            namn = [n for n in arkiv.namelist() if n.lower().endswith(".qgs")]
            if not namn:
                continue
            xml = arkiv.read(namn[0]).decode("utf-8")
        brist = set()
        for sokvag in re.findall(r"<editform[^>]*>([^<]+)</editform>", xml):
            sokvag = html.unescape(sokvag.strip())
            fil = Path(sokvag)
            if not fil.is_absolute():
                fil = arbetsmapp / sokvag
            if not fil.exists():
                brist.add(fil.name)
        if brist:
            saknas[projekt.name] = sorted(brist)
    return saknas


def namnge_efter_lan(arbetsmapp: Path | str, arbetsfil: Path, lan, datum: str):
    """Ger arbetsfilen och projektet lanets namn och uttagets datum.

    `lan` ar ett lan eller flera -- ett uttag over lansgransen bar bada.

    Mappen bar dem redan. Filerna gjorde det inte, och tre oppna arbeten i
    QGIS gav tre `lamningar.gpkg` som inte gick att skilja at -- varken i
    fillistan eller i "senast anvanda".

    Det konstanta namnet fanns av ett skal som inte galler langre. Det var
    till for att projektet aldrig skulle behova skrivas om: den forra
    omgangen bakade in projektet i koden och skrev om det vid varje uttag,
    och darfor forsvann varje anpassning. Nu skrivs projektet anda -- av
    typlistan, av autotexten, av rutstorlekarna -- sa den ena
    strangersattningen till kostar ingenting.

    Att den ar farlig ar en annan sak. Missas en referens moter inventeraren
    "Handle Unavailable Layers" i stallet for en karta, och det har hant
    forr. Darfor rakningen efterat: staar det gamla namnet kvar nagonstans
    avbryts bytet med filerna ororda.
    """
    from arkstod import lan as lansmodul

    arbetsmapp = Path(arbetsmapp)
    nytt_gpkg = arbetsmapp / lansmodul.gpkg_namn(lan, datum)
    nya_namn: dict[str, Path] = {}

    for projekt in sorted(arbetsmapp.glob("*.qgz")):
        with zipfile.ZipFile(projekt) as arkiv:
            innehall = {p.filename: arkiv.read(p.filename) for p in arkiv.infolist()}
        skrivet = {}
        for namn, data in innehall.items():
            if namn.lower().endswith(".qgs"):
                xml = data.decode("utf-8").replace(arbetsfil.name, nytt_gpkg.name)
                if arbetsfil.name in xml:
                    raise ValueError(
                        f"{projekt.name} nämner {arbetsfil.name} efter bytet"
                    )
                data = xml.encode("utf-8")
            skrivet[namn] = data
        with zipfile.ZipFile(projekt, "w", zipfile.ZIP_DEFLATED) as arkiv:
            for namn, data in skrivet.items():
                arkiv.writestr(namn, data)

        nytt = arbetsmapp / f"{lansmodul.mappnamn(lan, datum)}.qgz"
        if nytt != projekt:
            projekt.rename(nytt)
        nya_namn[projekt.name] = nytt

    if nytt_gpkg != arbetsfil:
        arbetsfil.rename(nytt_gpkg)
    return nytt_gpkg, nya_namn
