# Ändringar

Version 1.4.7 är den första som ges ut offentligt. De tidigare delades som zip mellan kollegor. Till och med version 1.3.0 hette pluginet **Lämningsdatabas**, och till och med 1.4.6 hette pluginmappen `arkstod_falt`.

## 1.4.7 (2026-11-11)

**Den som har en äldre Fältfångst (`arkstod_falt`) installerad ska avinstallera den först.** De två är samma plugin och kan inte vara installerade samtidigt: båda lägger samma kod på QGIS sökväg, och den som laddas först vinner. Avinstallera `arkstod_falt`, starta om QGIS och installera sedan den här. Arbetsmappar och inställningar fungerar som förut.

- **Pluginmappen heter `faltfangst`.** Namnet i QGIS, menyn och knapparna är oförändrade. Zippen heter `faltfangst.zip` i varje version.
- **Äldre arbetsmappar fungerar som förut.** En arbetsmapp gjord med 1.4.6 öppnar, blanketten byggs och leveranslistan skrivs. Inställningarna (senast valda län och mapp) följer med, eftersom de inte är knutna till pluginmappens namn.
- **Fungerar i QGIS 4 (Qt 6).** I QGIS 4 gick uttagsdialogen inte att öppna. Resten av pluginet behövde inte ändras. Pluginet kräver nu QGIS 3.40 eller nyare; äldre versioner är inte prövade.
- **Ett nytt uttag öppnar zoomat till länets lämningar.** Förut öppnade varje uttag över samma ruta i Härjedalen, oavsett län, och kartan såg tom ut tills man zoomade till lagren. Med grannlän visas båda länen.
- **Mallprojektet bär inte längre namnet på den som sparade det.** Namnet följde förut med till varje arbetsmapp.
- **Rättat: leveranslistans rullista för lämningstyp** hade ett val som inte var en lämningstyp utan QGIS interna platshållare för tomt värde, `{2839923C-…}`. Den är borta ur listan, och en rättelse som bär den skrivs aldrig in i arbetsfilen. Tomt väljs med den tomma raden.
- **Rättat: systemets längd.** Utkastet till beskrivning och knappen *Mått ur geometrin* gav olika längd för samma fångstgropssystem, till exempel 126 och 145 m. Knappen mätte ytan, som ritas tio meter utanför groparna. Nu räknar båda på groparna, eftersom principen säger "hela systemets längd", och båda skriver längden i femtal: "ca 125 m l".
- **Rättat:** utkastet skrev "inbördes avstånd av 32–32 m" när alla avstånd var lika. Nu står det "32 m".
- **Rättat: *Geometrier till Fornreg* markerar zippen i Utforskaren.** När arbetsmappens namn hade ett mellanslag, vilket det alltid har, öppnades mappen Dokument i stället. En varning i loggen om en process som fortfarande kördes är också borta.
- **Fristående tillägg.** Beskrivningen säger uttryckligen att pluginet inte kommer från Riksantikvarieämbetet.
- **Bruksanvisningen** säger hur pluginet hämtas från GitHub. Skärmbilden av fliken Administrativt är omgjord.
- Stilmallens generator (`palett.py`) följer inte längre med. Den används bara när blanketten byggs.
- Provat utan gränssnitt i QGIS 3.44.14 och 4.2.3: pluginet laddar, ett uttag för Jämtland går igenom, projektet öppnar, blanketten byggs för punkt, linje och yta, ett fångstgropssystem skapas ur punkterna, och leveranslistan skrivs. Provat i QGIS-fönstret i 3.44.14.

## 1.4.6 (2026-09-24)

- **Grannlän.** Ett uttag kan omfatta två län, när arbetet går över länsgränsen. Lämningar som ligger på gränsen står i båda länens uttag men kommer med en gång. Regionala tillägg följer med för båda länen.
- **Sökvägens längd prövas innan något hämtas.** Windows klarar 260 tecken. Förut föll uttaget i sista steget och lämnade en halvfärdig mapp.
- **Uttaget varnar om blanketten saknas** i arbetsmappen. Varningarna visas i en ruta som måste klickas bort, i stället för i en logg som stängdes direkt.

## 1.4.2–1.4.5 (2026-09-15 – 2026-09-17)

- Projektets sökvägar hålls relativa vid varje sparning, inte bara vid uttaget, så att arbetsmappen går att kopiera.
- Kontrollen känner igen en färdig arbetsmapp, inte bara en halvbyggd.
- Licensen är GNU GPL version 2 eller senare.
- Om-rutan och bruksanvisningen säger att det är en betaversion.

## 1.4.1 (2026-09-08)

- Platshållaradresser borttagna ur pluginets metadata.

## 1.4.0 (2026-09-04)

- **Pluginet heter Fältfångst** (hette Lämningsdatabas). Om-rutan säger vilken version av lämningstypslistan, exempelsamlingen och fälthandboken verktyget svarar utifrån.
- Blanketten har fem flikar: Lämningen, Bedömning, Platsen, Administrativt och Uppslag.
- Beskrivningens första ord föreslås ur Exempelsamlingen när lämningstypen väljs, och mått kan hämtas ur geometrin med längdriktning.
- *Vad återstår?* visar vad som saknas innan du lämnar området.
- Skadebeskrivning krävs vid åverkan.
- Ett klick på en lämning öppnar blanketten direkt.

## 1.3.0 (2026-09-01)

- **Sammansatta lämningar.** Fångstgropssystem och andra sammansatta lämningar föreslås ur punkterna, med yta och utkast till beskrivning.
- **Geometrier till Fornreg** som zippade shapefiler.
- **Uppslagsboken**: lämningstypslistan som en sida att läsa, i varje arbetsmapp.
- Bruksanvisning och handbok följer med i varje arbetsmapp.
- Leveranslistan går att rätta i, har en sammanräkning överst och frågar när en ny lämning ligger intill en registrerad.
- Bedömningen låses där lämningen inte finns kvar, till exempel vid *Helt undersökt*.
- Uttaget föreslår mappnamn: län och datum.
- Autotext: beskrivningen kan ärvas från föregående lämning av samma typ.
- Tomma fält visas tomma i stället för som ordet NULL.
- Besöket stämplas med datum och löpnummer vid första ändringen.

## 1.2.0 (2026-08-24)

- **Leveranslistan** ersätter kvällsvyn: det jobbet ändrat, i Fornregs ordning, med kontrollerna vid det fält de gäller.
- Blanketten är ritad för en fältdator.
- Motiveringsfältet och påminnelsen om när dateringen måste motiveras.
- Lämningstypslistans "Avser inte"-satser visas vid typvalet.
- Ett uttag ersätter aldrig ett tidigare: varje arbete får en egen mapp.

## 1.1.0 (2026-08-24)

- Pluginet bär lämningstypsdatabasens nya modell. Den installerade versionen låg kvar på den första.

## 1.0.0 (2026-08-21)

- Första versionen: en knapp som hämtar länsuttaget från Riksantikvarieämbetet, bygger ut det och öppnar projektet.
