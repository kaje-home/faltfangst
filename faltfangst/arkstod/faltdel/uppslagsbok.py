"""Uppslagsboken: lamningstypslistan att laesa, inte att blaeddra i.

Attributtabellerna gick att stada -- se `uppslagsvy.py` -- men ett rutnaet
foerblir ett rutnaet. Naer man faktiskt behoever *laesa* en definition eller
jaemfoera tva typer aer det en bok man vill ha.

Samma konstruktion som leveranslistan, och av samma skael: en fristaende
HTML-fil i arbetsmappen. Den foeljer med naer mappen kopieras, oeppnas i vilken
webblaesare som helst utan QGIS eller Python, och fungerar utan taeckning.

**Vad boken aer:** formulaerets fyra uppslag -- Uteslut, Matt, Exempel, Listan
saeger -- plus de tre texter som med flit inte staar i formulaeret: RAAE:s
definition, kommentar och antikvariska bedoemning, ordagrant.

Skalet till att de tre inte staar i blanketten haaller: behoever man laesa
definitionen paa plats aer typvalet aendaa osaekert, och daa ska man stanna upp
och slaa upp -- inte laesa foerbi i en ruta bredvid attributen. Boken aer det
staellet att slaa upp.

Allt laeses ur arbetsfilens egna `ark_`-tabeller. Boken kan alltsa aldrig saega
naagot annat aen formulaeret i samma mapp.
"""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

FILNAMN = "uppslagsbok.html"


@dataclass(frozen=True)
class Exempel:
    """Ett beskrivningsexempel med den nyckel det gaeller for."""

    nyckel: str
    text: str


@dataclass
class Uppslag:
    """En lamningstyp, allt som finns om den."""

    benamning: str
    sida: str = ""
    definition: str = ""
    kommentar: str = ""
    bedomning: str = ""
    uteslut: str = ""
    mattregel: str = ""
    motivering: str = ""
    sammansatt: bool = False
    exempel: list[Exempel] = field(default_factory=list)
    jfr: list[str] = field(default_factory=list)
    egenskaper: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class Bok:
    gpkg: Path
    listversion: str = ""
    uttagsdatum: str = ""
    uppslag: list[Uppslag] = field(default_factory=list)


def _text(varde: object) -> str:
    return str(varde).strip() if varde not in (None, "") else ""


def _dela_exempel(samlad: str) -> list[Exempel]:
    """Delar ark_anvisning.exempel i sina delar.

    Exporten skriver ett exempel per stycke med nyckeln foerst, avskild med
    tankstreck: "Bytesdjur: Alg/ren, Form: Rund — Fangstgrop, rund, 4 m ...".
    Typer utan egenskapsberoende exempel har ingen nyckel alls.
    """
    exempel = []
    for stycke in _text(samlad).split("\n\n"):
        stycke = stycke.strip()
        if not stycke:
            continue
        nyckel, avskiljare, text = stycke.partition(" — ")
        if avskiljare and ":" in nyckel and len(nyckel) < 120:
            exempel.append(Exempel(nyckel.strip(), text.strip()))
        else:
            exempel.append(Exempel("", stycke))
    return exempel


def _finns(anslutning: sqlite3.Connection, tabell: str) -> bool:
    return bool(
        anslutning.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabell,)
        ).fetchone()
    )


def bok(gpkg: Path | str) -> Bok:
    """Laeser uppslagen ur arbetsfilen."""
    gpkg = Path(gpkg)
    anslutning = sqlite3.connect(gpkg)
    anslutning.row_factory = sqlite3.Row
    try:
        if not _finns(anslutning, "ark_lamningstyp"):
            raise ValueError(
                f"{gpkg.name} saknar ark_lamningstyp — är det en arbetsfil?"
            )
        resultat = Bok(gpkg)

        if _finns(anslutning, "ark_modell"):
            rad = anslutning.execute(
                "SELECT listversion, hamtdatum FROM ark_modell LIMIT 1"
            ).fetchone()
            if rad:
                resultat.listversion = _text(rad["listversion"])
                resultat.uttagsdatum = _text(rad["hamtdatum"])

        anvisningar = {}
        if _finns(anslutning, "ark_anvisning"):
            for rad in anslutning.execute("SELECT * FROM ark_anvisning"):
                anvisningar[rad["lamningstyp"]] = rad

        jfr: dict[str, list[str]] = {}
        if _finns(anslutning, "ark_jfr"):
            for rad in anslutning.execute("SELECT fran, till FROM ark_jfr"):
                jfr.setdefault(rad["fran"], []).append(rad["till"])

        egenskaper: dict[str, dict[str, list[str]]] = {}
        if _finns(anslutning, "ark_egenskapsvarde"):
            for rad in anslutning.execute(
                "SELECT benamning, typnamn, varde FROM ark_egenskapsvarde"
                " ORDER BY benamning, typnamn, ordning"
            ):
                per_typ = egenskaper.setdefault(rad["benamning"], {})
                per_typ.setdefault(rad["typnamn"], []).append(rad["varde"])

        for rad in anslutning.execute(
            "SELECT * FROM ark_lamningstyp ORDER BY benamning COLLATE NOCASE"
        ):
            namn = rad["benamning"]
            anvisning = anvisningar.get(namn)
            resultat.uppslag.append(
                Uppslag(
                    benamning=namn,
                    sida=_text(rad["sida"]),
                    definition=_text(rad["definition"]),
                    kommentar=_text(rad["kommentar"]),
                    bedomning=_text(rad["bedomning"]),
                    sammansatt=bool(rad["sammansatt"]),
                    uteslut=_text(anvisning["uteslut"]) if anvisning else "",
                    mattregel=_text(anvisning["mattregel"]) if anvisning else "",
                    motivering=_text(anvisning["motivering"]) if anvisning else "",
                    exempel=(
                        _dela_exempel(anvisning["exempel"]) if anvisning else []
                    ),
                    jfr=sorted(jfr.get(namn, [])),
                    egenskaper=sorted(egenskaper.get(namn, {}).items()),
                )
            )
        return resultat
    finally:
        anslutning.close()


def _id(benamning: str) -> str:
    """Ett ankarnamn som taal aao och mellanslag."""
    return "t-" + "".join(
        tecken if tecken.isalnum() else "-" for tecken in benamning.lower()
    )


def _avsnitt(rubrik: str, kropp: str, klass: str = "") -> str:
    if not kropp:
        return ""
    marke = f' class="{klass}"' if klass else ""
    return f"<section{marke}><h3>{html.escape(rubrik)}</h3>{kropp}</section>"


def _stycken(text: str) -> str:
    return "".join(
        f"<p>{html.escape(stycke.strip())}</p>"
        for stycke in text.split("\n")
        if stycke.strip()
    )


def _uppslag_html(uppslag: Uppslag) -> str:
    delar = []

    if uppslag.motivering:
        delar.append(f'<p class="besked">{html.escape(uppslag.motivering)}</p>')

    delar.append(_avsnitt("Definition", _stycken(uppslag.definition)))
    delar.append(_avsnitt("Kommentar", _stycken(uppslag.kommentar)))
    delar.append(
        _avsnitt("Antikvarisk bedömning", _stycken(uppslag.bedomning), "raa")
    )
    delar.append(_avsnitt("Uteslut", _stycken(uppslag.uteslut), "uteslut"))
    delar.append(_avsnitt("Mått", _stycken(uppslag.mattregel), "matt"))

    if uppslag.exempel:
        rader = []
        for ett in uppslag.exempel:
            nyckel = (
                f'<span class="nyckel">{html.escape(ett.nyckel)}</span>'
                if ett.nyckel
                else ""
            )
            rader.append(f"<p>{nyckel}{html.escape(ett.text)}</p>")
        delar.append(_avsnitt("Exempel på beskrivning", "".join(rader), "exempel"))

    if uppslag.jfr:
        lankar = " ".join(
            f'<a href="#{_id(namn)}">{html.escape(namn)}</a>' for namn in uppslag.jfr
        )
        delar.append(_avsnitt("Jämför med", f'<p class="jfr">{lankar}</p>'))

    if uppslag.egenskaper:
        rader = "".join(
            f"<p><b>{html.escape(typ)}:</b> {html.escape(', '.join(varden))}</p>"
            for typ, varden in uppslag.egenskaper
        )
        delar.append(_avsnitt("Egenskaper", rader, "egenskap"))

    marken = []
    if uppslag.sida:
        marken.append(f'<span class="sida">s. {html.escape(uppslag.sida)}</span>')
    if uppslag.sammansatt:
        marken.append('<span class="markering">sammansatt typ</span>')

    return (
        f'<article id="{_id(uppslag.benamning)}"'
        f' data-namn="{html.escape(uppslag.benamning.lower())}">'
        f"<h2>{html.escape(uppslag.benamning)} {' '.join(marken)}</h2>"
        f"{''.join(delar)}"
        "</article>"
    )


def html_sida(bokens: Bok) -> str:
    """Uppslagsboken som en fristaende HTML-fil."""
    return _MALL.format(
        antal=len(bokens.uppslag),
        listversion=html.escape(bokens.listversion or "5.0"),
        uttagsdatum=html.escape(bokens.uttagsdatum or "okänt"),
        skapad=date.today().isoformat(),
        uppslag="\n".join(_uppslag_html(ett) for ett in bokens.uppslag),
    )


def skriv(gpkg: Path | str) -> Path:
    """Skriver uppslagsboken bredvid arbetsfilen och returnerar sokvagen."""
    gpkg = Path(gpkg)
    mal = gpkg.parent / FILNAMN
    mal.write_text(html_sida(bok(gpkg)), encoding="utf-8")
    return mal


_MALL = """<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Uppslagsbok — Lämningstypslistan {listversion}</title>
<style>
  :root {{
    --papper: #fff; --bakgrund: #edeae4; --ram: #d8d4cc;
    --tag: #6b6459; --text: #23201c;
    --raa: #2f4858; --raayta: #eef3f6;
    --uteslut: #7a5c00; --uteslutyta: #fbf6e6;
    --matt: #3f5c3a; --mattyta: #f0f5ee;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bakgrund); color: var(--text);
    font: 16px/1.55 Georgia, "Times New Roman", serif;
  }}
  header {{
    position: sticky; top: 0; z-index: 5;
    background: var(--papper); border-bottom: 2px solid var(--ram);
    padding: 7px 16px 8px;
  }}
  /* Rubrik och stampel delar rad: pa en tiotumsskarm ar varje rad i
     sidhuvudet en rad mindre uppslag. */
  .topp {{
    display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
  }}
  h1 {{ font-size: 1.05rem; margin: 0; }}
  .stampel {{ font-size: .76rem; color: var(--tag); }}
  #sok {{
    width: 100%; margin-top: 6px; padding: 7px 12px; font-size: 1.02rem;
    font-family: inherit; border: 2px solid var(--ram); border-radius: 4px;
    background: var(--papper); color: inherit;
  }}
  #sok:focus {{ outline: 2px solid var(--raa); border-color: var(--raa); }}
  /* Raknaren tar ingen plats forran den har nagot att saga. */
  #raknare {{ font-size: .78rem; color: var(--tag); }}
  #raknare:empty {{ display: none; }}
  /* Radlangden ar det som avgor om en text gar att lasa. Georgia ger runt
     70 tecken pa 60ch, vilket ar dar ogat vill ha den. */
  main {{ padding: 12px 16px 60px; max-width: 60ch; margin: 0 auto; }}
  article {{
    background: var(--papper); border: 1px solid var(--ram);
    border-radius: 5px; padding: 12px 16px; margin-bottom: 14px;
  }}
  article[hidden] {{ display: none; }}
  h2 {{
    font-size: 1.25rem; margin: 0 0 8px;
    border-bottom: 1px solid var(--ram); padding-bottom: 6px;
  }}
  h3 {{
    font-size: .78rem; text-transform: uppercase; letter-spacing: .06em;
    color: var(--tag); margin: 14px 0 4px; font-family: system-ui, sans-serif;
  }}
  p {{ margin: 0 0 8px; }}
  section p:last-child {{ margin-bottom: 0; }}
  .sida, .markering {{
    float: right; font-size: .72rem; color: var(--tag); font-weight: normal;
    font-family: system-ui, sans-serif; margin-left: 8px; padding-top: 6px;
  }}
  .besked {{
    font-size: .9rem; color: var(--tag);
    font-family: system-ui, sans-serif;
  }}
  section.raa, section.uteslut, section.matt, section.exempel {{
    border-left: 3px solid var(--ram); padding-left: 12px; margin-top: 14px;
  }}
  section.raa {{ border-color: var(--raa); background: var(--raayta); }}
  section.uteslut {{ border-color: var(--uteslut); background: var(--uteslutyta); }}
  section.matt {{ border-color: var(--matt); background: var(--mattyta); }}
  section.raa, section.uteslut, section.matt {{
    padding: 8px 12px; border-radius: 0 4px 4px 0;
  }}
  section.raa h3 {{ color: var(--raa); margin-top: 0; }}
  section.uteslut h3 {{ color: var(--uteslut); margin-top: 0; }}
  section.matt h3 {{ color: var(--matt); margin-top: 0; }}
  .nyckel {{
    display: block; font-size: .74rem; color: var(--tag);
    font-family: system-ui, sans-serif; text-transform: uppercase;
    letter-spacing: .04em;
  }}
  section.exempel p {{ margin-bottom: 12px; }}
  .jfr a, .egenskap b {{ font-family: system-ui, sans-serif; font-size: .9rem; }}
  .jfr a {{
    display: inline-block; margin: 0 6px 4px 0; padding: 2px 8px;
    background: var(--bakgrund); border-radius: 3px;
    color: var(--raa); text-decoration: none;
  }}
  .jfr a:hover, .jfr a:focus {{ text-decoration: underline; }}
  .egenskap p {{ font-size: .92rem; }}
  #tomt {{ color: var(--tag); font-style: italic; }}
  @media print {{
    header {{ position: static; }} #sok, #raknare {{ display: none; }}
    body {{ background: #fff; }} article {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
<header>
  <div class="topp">
    <h1>Uppslagsbok — Lämningstypslistan {listversion}</h1>
    <span class="stampel">{antal} lämningstyper · uttag {uttagsdatum} · skriven {skapad}</span>
  </div>
  <input id="sok" type="search" placeholder="Sök lämningstyp eller ord i texten…"
         autocomplete="off" autofocus>
  <div id="raknare"></div>
</header>
<main>
{uppslag}
<p id="tomt" hidden>Ingen lämningstyp matchar sökningen.</p>
</main>
<script>
(function () {{
  var ruta = document.getElementById('sok');
  var raknare = document.getElementById('raknare');
  var tomt = document.getElementById('tomt');
  var boken = document.querySelector('main');
  var uppslag = Array.prototype.slice.call(document.querySelectorAll('article'));

  uppslag.forEach(function (ett) {{
    ett.dataset.text = ett.textContent.toLowerCase();
  }});

  function visa() {{
    var fraga = ruta.value.trim().toLowerCase();
    var traffar = 0;
    var pa_namn = [];
    var pa_text = [];
    uppslag.forEach(function (ett) {{
      if (!fraga) {{ ett.hidden = false; traffar++; return; }}
      if (ett.dataset.namn.indexOf(fraga) !== -1) {{
        ett.hidden = false; pa_namn.push(ett); traffar++;
      }} else if (ett.dataset.text.indexOf(fraga) !== -1) {{
        ett.hidden = false; pa_text.push(ett); traffar++;
      }} else {{
        ett.hidden = true;
      }}
    }});

    // Namnträffar först. Skriver man "kolningsanläggning" ska den typen stå
    // överst, inte de typer som råkar nämna den i sin text.
    var ordning = fraga ? pa_namn.concat(pa_text) : uppslag;
    ordning.forEach(function (ett) {{ boken.appendChild(ett); }});

    tomt.hidden = traffar > 0;
    boken.appendChild(tomt);
    raknare.textContent = fraga
      ? traffar + ' av ' + uppslag.length + ' visas'
      : '';
  }}

  ruta.addEventListener('input', visa);
  // En traff pa namnet ska ga att oppna direkt fran Jfr-lankarna.
  window.addEventListener('hashchange', function () {{
    if (ruta.value) {{ ruta.value = ''; visa(); }}
    var mal = document.getElementById(location.hash.slice(1));
    if (mal) mal.scrollIntoView();
  }});
}})();
</script>
</body>
</html>
"""
