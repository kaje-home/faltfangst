"""Sveriges lan, som ett begrepp i stallet for en strang i en bat-fil.

Verktyget ska fungera i alla lan. Lamningstypslistan ar nationell, och
exporten till GPKG bryr sig inte om vilket uttag den skriver i -- men
lansuttaget hamtas per lan, och namnkonventionerna maste stamma med dem
pluginen redan anvander. Darfor ligger listan har, en gaang, i stallet for
utspridd over ett migreringsskript och en pluginmodul.

Det som daremot ar lansbundet i sak ar tolkningsskiktet: Lamningstypslistan
bar en mellansvensk normalbild i sina typdefinitioner, och den racker inte som
enda underlag i Jamtland. Ett sadant skikt skrivs per lan och far aldrig
forvaxlas med RAA:s normerande text. Jamtland ar forst, inte enda.
"""

from __future__ import annotations

# Ordningen ar RAA:s egen, och stavningen ar den som gaar in i URL:en.
# Samma lista som pluginens ALLA_LAN -- andras den ena maste den andra folja.
LAN: tuple[str, ...] = (
    "blekinge",
    "dalarna",
    "gotland",
    "gävleborg",
    "halland",
    "jämtland",
    "jönköping",
    "kalmar",
    "kronoberg",
    "norrbotten",
    "skåne",
    "stockholm",
    "södermanland",
    "uppsala",
    "värmland",
    "västerbotten",
    "västernorrland",
    "västmanland",
    "västra götaland",
    "örebro",
    "östergötland",
)

# Den aldre `lamningar/`-sokvagen ger 404. Filnamnen ar gemena och
# URL-kodade; att koda snedstreck eller kolon ger ett tyst fel av samma slag
# som XYZ-URI:er i QGIS.
NEDLADDNING = "https://pub.raa.se/nedladdning/datauttag/lamningar_v1/lan/"

# Mellanslag ar understreck i filnamnet, inte %20. Det galler ett enda lan --
# Vastra Gotaland -- och gav 404 anda tills det provades mot RAA:s katalog.
# Pluginens migrera.py kodar det som %20 och kan alltsa inte hamta det lanet.
_KODNING = {"ä": "%c3%a4", "å": "%c3%a5", "ö": "%c3%b6", " ": "_"}


def normalisera(namn: str) -> str:
    """Gor "Jämtland", "JÄMTLAND" och "jämtland" till samma sak."""
    return " ".join(namn.split()).casefold()


def ar_lan(namn: str) -> bool:
    return normalisera(namn) in LAN


def kodat(lan: str) -> str:
    """Lansnamnet som det stavas i RAA:s filnamn."""
    text = normalisera(lan)
    for tecken, kod in _KODNING.items():
        text = text.replace(tecken, kod)
    return text


def url(lan: str) -> str:
    """Nedladdningslanken for ett lansuttag."""
    if not ar_lan(lan):
        raise ValueError(f"okänt län: {lan}")
    return f"{NEDLADDNING}l%c3%a4mningar_l%c3%a4n_{kodat(lan)}.gpkg"


def lista(lan) -> list[str]:
    """Ett lan eller flera, normaliserade och utan upprepning.

    Ett uttag kan tacka tva lan nar arbetet gaar over lansgransen -- en
    kraftledning bryr sig inte om var den gaar. Forsta lanet ar det man
    valde forst, och ordningen halls.
    """
    if isinstance(lan, str):
        lan = [lan]
    valda: list[str] = []
    for namn in lan:
        namn = normalisera(namn)
        if namn and namn not in valda:
            valda.append(namn)
    return valda


def benamning(lan) -> str:
    """"Jämtland", "Jämtland och Västernorrland" -- som man sager det."""
    namn = [n.title() for n in lista(lan)]
    if len(namn) <= 1:
        return "".join(namn)
    return ", ".join(namn[:-1]) + " och " + namn[-1]


def gpkg_namn(lan, datum: str) -> str:
    return f"lämningar_län_{'_'.join(lista(lan))}_{datum}.gpkg"


def mappnamn(lan, datum: str) -> str:
    return f"Lämningsdatabas {benamning(lan)} {datum}"
