# Fältfångst

Ett QGIS-plugin för arkeologisk inventering och utredning. Det hämtar Riksantikvarieämbetets uttag över registrerade lämningar för ett län och gör i ordning ett fältprojekt: en lämningsdatabas, en blankett som öppnas när du prickar en lämning, och en leveranslista inför registreringen i Fornreg.

Pluginet är ett fristående tillägg. Det kommer inte från Riksantikvarieämbetet eller någon annan myndighet.

**Det räknar och det föreslår. Det avgör aldrig.** Antal, avstånd, mått och datum sköter verktyget. Om en lämning är en fornlämning, om fem gropar bildar ett system och om en beskrivning stämmer avgör du som var på platsen.

## ⬇️ [Ladda ner senaste versionen](https://github.com/kaje-home/faltfangst/releases/latest/download/faltfangst.zip)

En zip-fil som installeras i QGIS: **Insticksprogram → Hantera och installera insticksprogram… → Installera från ZIP**. Experimentella insticksprogram måste vara tillåtna (fliken *Inställningar*). Kräver QGIS 3.40 eller nyare. Provat i QGIS 3.44 och 4.2.

**Som förråd i QGIS.** I stället för att hämta zippen kan du lägga in pluginets förråd: *Insticksprogram → Hantera och installera insticksprogram… → Inställningar → Lägg till*, med adressen `https://raw.githubusercontent.com/kaje-home/faltfangst/main/plugins.xml`. Pluginet står då i listan över insticksprogram, och nya versioner visas som uppdateringar. Experimentella insticksprogram måste vara tillåtna även då.

**Har du en äldre Fältfångst installerad? Avinstallera den först.** Till och med version 1.4.6 hette pluginmappen `arkstod_falt`, och den delades som zip mellan kollegor. Det är samma plugin, och **de två kan inte vara installerade samtidigt**: båda lägger samma kod på QGIS sökväg, och den som laddas först vinner. Avinstallera `arkstod_falt` under *Insticksprogram → Hantera och installera insticksprogram… → Installerade*, starta om QGIS och installera sedan den här. Dina arbetsmappar och inställningar fungerar som förut.

Det här är en beta. Den är prövad i skarpa uppdrag i Jämtland, men inte bred nog för att kallas färdig. Kontrollera alltid det som ska till Fornreg.

## Vad pluginet gör

- **Uttaget.** Du väljer län och en ny mapp. Pluginet hämtar länets registrerade lämningar från Riksantikvarieämbetets öppna data, bygger ut dem till en arbetsfil och öppnar projektet. Går arbetet över länsgränsen väljer du ett grannlän, så hamnar båda länens lämningar i samma arbetsfil.
- **Blanketten.** När du prickar en lämning öppnas en blankett med fem flikar: Lämningen, Bedömning, Platsen, Administrativt och Uppslag. Bredvid det du fyller i står beskrivningsprincipen och färdiga exempel för den lämningstyp du valt, vad typen ska hållas isär från, och när antagandet om tillkomsttid måste motiveras.
- **Sammansatta lämningar.** Pluginet kan kedja ihop dina punkter till fångstgropssystem och andra sammansatta lämningar på det avstånd lämningstypslistan anger, lägga ytan runt dem och skriva ett utkast till beskrivning.
- **Leveranslistan.** En fristående sida med allt du ändrat sedan uttaget, i den ordning Fornreg frågar efter det, med en kopieringsknapp per fält. Den säger ifrån när en text avviker från fälthandbokens form, när en motivering saknas och när en ny lämning ligger intill en som redan är registrerad.
- **Geometrierna.** Zippade shapefiler att ladda upp i Fornreg.
- **Uppslagsboken.** Hela lämningstypslistan som en sida att läsa, i varje arbetsmapp.

Arbetsmappen är en enhet. Kopiera den till fältdatorn som den är, så fungerar allt utan täckning.

## Snabbstart

1. Installera pluginet enligt ovan. Du får menyn **Fältfångst** och knappar i verktygsraden.
2. **Fältfångst → Lämningsdatabas — nytt uttag.** Välj län, eventuellt grannlän, och var mappen ska ligga. Uttaget kräver internet; gör det hemma, inte i skogen.
3. Tryck **Hämta och öppna**. Det tar några minuter. Projektet öppnas zoomat till länets lämningar.
4. I fält: sätt en punkt, en linje eller en yta i rätt lager, så öppnas blanketten. Klickar du på en befintlig lämning öppnas dess blankett.
5. På kontoret: **Fältfångst → Leveranslista — inför registrering i Fornreg** och **Geometrier till Fornreg — zippade shapefiler**.

Hela bruksanvisningen ligger som PDF i [`dokument/`](dokument/). Samma bruksanvisning och en handbok om hur verktyget resonerar följer med i varje arbetsmapp, som `bruksanvisning.html` och `handbok.html`.

## Hör ihop med Arkeologiskt inventeringsunderlag

[Arkeologiskt inventeringsunderlag](https://github.com/kaje-home/arkeologiskt-inventeringsunderlag) är ett eget plugin. Det gör i ordning höjdmodell, skuggbilder, ortofoto, ekonomiska kartan, ortnamn och jordarter över ett arbetsområde. De två fungerar var för sig, men är gjorda för att användas ihop:

- Gör uttaget för inventeringsunderlaget inifrån Fältfångsts projekt. Då räknas de registrerade lämningarna i arbetsområdet med.
- Lägg underlaget i fältfångstmappen, förslagsvis `<arbete>/underlag/<beteckning>/`. Då håller sökvägarna när mappen kopieras till fältdatorn.

I vilken ordning man arbetar står i [arbetsordningen](https://github.com/kaje-home/arkeologiskt-inventeringsunderlag/blob/main/dokument/Arbetsordning_Faltfangst_och_Inventeringsunderlag.pdf).

## Data och licens

Pluginet bär med sig en databas, `data/lamningstyper.db`, och hämtar lämningarna vid varje uttag.

| Källa | Vad | Villkor |
|---|---|---|
| **Riksantikvarieämbetet** | *Lista med lämningstyper och antikvarisk praxis*, version 5.0 (2021): lämningstyper, egenskaper, definitioner, antikvarisk bedömning, Jfr-hänvisningar och "Avser inte"-satser. **Följer med pluginet** i bearbetad form. | CC BY enligt Riksantikvarieämbetets villkor för raa.se. Dokumentet anger ingen egen licens. Källa: Riksantikvarieämbetet. Texten är återgiven ordagrant. |
| **Riksantikvarieämbetet** | *Exempelsamling*, version 1.0 (2008), del 2 av *Handledning för inventering och dokumentation av forn- och kulturlämningar för FMIS*: beskrivningsprinciper och färdiga beskrivningar per lämningstyp. **Följer med pluginet** i bearbetad form. | CC BY enligt Riksantikvarieämbetets villkor för raa.se. Dokumentet anger ingen egen licens. Källa: Riksantikvarieämbetet. Texten är återgiven ordagrant. |
| **Jamtli** | *Fälthandbok i arkeologisk inventering* 2.0 (2023): formregler för mått, uteslutningar och förtydliganden. **Följer med pluginet** i bearbetad form. | CC BY. Källa: Jamtli. |
| **Riksantikvarieämbetet** | Öppna länsuttag ur Kulturmiljöregistret (KMR): registrerade lämningar med geometrier. Hämtas vid varje uttag, följer inte med pluginet. | Riksantikvarieämbetets öppna data. Se deras villkor. |

Riksantikvarieämbetets villkor står på sidan [Upphovsrätt på raa.se](https://www.raa.se/om-riksantikvarieambetet/om-webbplatsen/upphovsratt-pa-raa-se/). De två dokumenten är hämtade från raa.se 2026-08-20:

- Lämningstypslistan 5.0: <https://www.raa.se/app/uploads/2025/06/Lamningstypslistan-5.0.pdf>
- Exempelsamlingen 1.0, red. Anna-Lena Olsson: <https://www.raa.se/app/uploads/2025/12/Exempelsamling-ver-1.0.pdf>

`lamningstyper.db` är byggd ur de tre första källorna. Byggverktyget, som läser PDF-filerna, ingår inte i det här repot, så **databasen går inte att bygga om ur det som ligger här**. Vilken version av lämningstypslistan databasen bygger på står i *Fältfångst → Om Fältfångst …* och i varje uttags uppslagsbok.

Blanketten visar alltid vilken källa ett besked kommer från. Riksantikvarieämbetets normerande text och fälthandbokens regionala erfarenhet hålls isär.

**Koden** är fri programvara under **GNU GPL version 2 eller senare**, se [LICENSE](LICENSE). **Bruksanvisningen** är CC BY 4.0.

## När något går fel

*Vy → Paneler → Loggmeddelanden*. Skriv en [felanmälan](https://github.com/kaje-home/faltfangst/issues) och klistra in det som står där, tillsammans med vad du försökte göra.

Öppnas inte blanketten när du klickar på en lämning, och QGIS säger att funktionen `nar_formularet_oppnas` inte hittas? Då är pluginet inte påslaget. Bocka i *Fältfångst* under *Insticksprogram → Hantera och installera insticksprogram… → Installerade*.

## Ändringar

Se [CHANGELOG.md](CHANGELOG.md).

© 2026 Karl-Johan Olofsson
