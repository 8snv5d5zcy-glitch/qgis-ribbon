# Mit dem Ribbon arbeiten

[Inhalt](index.md)

![Das Ribbon mit dem Tab Karte](../images/de/tab_map.png)

Das Ribbon besteht aus der **Kopfzeile** (Schnellzugriffsleiste, Tabs, Befehlssuche, Knöpfe zum Minimieren und für die Hilfe) und der **Ribbon-Fläche** mit den Gruppen des gewählten Tabs.

## Tabs

| Tab | Gruppen |
|---|---|
| Karte | Zwischenablage, Navigieren, Layer, Auswahl, Abfragen, Beschriftung |
| Einfügen | Projekt, Neue Layer, Stile, Favoriten |
| Analyse | Geoverarbeitung, Werkzeuge |
| Ansicht | Verknüpfen, Fenster, Barrierefreiheit, Navigation |
| Bearbeiten | Zwischenablage, Bearbeitung, Einrasten, Konstruktion, Objekte, Auswahl, Werkzeuge, Höhe |
| Bilddaten | Ausrichten, Analyse |
| Teilen | Paket, Speichern als, Ausgabe |
| Erweiterungen | Befehle installierter Plugins, siehe [Erweiterungen](extensions.md) |

![Der Tab Bearbeiten](../images/de/tab_edit.png)

Beginnt die Bearbeitung eines Layers, wechselt das Ribbon zum Tab **Bearbeiten**. Aus einem eigenen Tab (siehe [Ribbon anpassen](customize.md)) wechselt es nicht; dort bleibt Ihr Arbeitsablauf stehen.

In **Bearbeitung** wirken **Bearbeiten**, **Speichern** und **Verwerfen** nur auf den aktiven Layer; nach Speichern oder Verwerfen bleibt die Bearbeitung an. **Alle speichern** und **Alle verwerfen** wirken auf alle Layer in Bearbeitung. Vor dem Verwerfen kommt eine Rückfrage.

**Konstruktion › Erweiterte Digitalisierung** schaltet die Konstruktionshilfen ein oder aus (Abstand, Winkel, Koordinaten beim Digitalisieren). Der Schalter ist bedienbar, solange ein Werkzeug aktiv ist, das sie unterstützt, etwa **Erstellen** oder **Ändern**. Solange er an ist, öffnet QGIS das Panel bei jedem solchen Werkzeug; **Konstruktionspanel** blendet es ein oder aus. Die kleinen Icons in **Einrasten** schalten Spurverfolgung, Selbsteinrasten und das Einrasten auf Schnittpunkte.

## Kontext-Tabs

Manche Tabs erscheinen nur, wenn sie zum aktiven Layer im Bedienfeld Layer passen. Sie stehen rechts in einem farbigen Rahmen mit dem Namen ihres Kontexts:

- **Vektorlayer:** Darstellung, Beschriftung, Daten
- **Tabelle** (Layer ohne Geometrie): Daten
- **Rasterlayer**, **Vektorkacheln**, **Punktwolke**, **Netz:** Darstellung
- **Gruppe** (eine Gruppe im Bedienfeld Layer gewählt): Darstellung

![Kontext-Tab Darstellung eines Vektorlayers](../images/de/contextual.png)

**Darstellung** hat in jedem Kontext dieselben ersten Gruppen:

- **Sichtbarkeitsbereich:** größter und kleinster Maßstab, in dem der Layer gezeichnet wird.
- **Effekte:** Deckkraft und Mischmodus des Layers mit den Layern darunter (zum Beispiel *Multiplizieren* für ein Relief unter einer Karte). **Objekt-Mischmodus** (nur Vektorlayer) mischt die Objekte des Layers untereinander.
- **Vergleichen:** **Wischen** ist ein Kartenwerkzeug: Mit gedrückter Maustaste über die Karte ziehen, hinter der Kante ist der Layer ausgeblendet und gibt den Blick auf die Layer darunter frei. Die Zugrichtung bestimmt, ob die Kante senkrecht oder waagerecht liegt; beim Loslassen ist der Layer wieder ganz zu sehen. **Flimmern** blendet den Layer im eingestellten Takt (Millisekunden) aus und ein, bis es wieder ausgeschaltet oder ein anderer Layer gewählt wird. Beides ändert weder die Layerliste noch das Projekt.

Danach folgen die Gruppen des Layertyps, zum Beispiel **Aggregation** für Punktlayer (Punktcluster, Punktverdrängung, Heatmap; **Keine** stellt die vorige Darstellung wieder her), die **Darstellungsart**, **Punktgröße** und der **maximale Fehler** einer Punktwolke oder die dargestellten Datensätze (**Skalar**, **Vektoren**) und das **Netzgitter** eines Netzes.

**Gruppe:** Deckkraft, Mischmodus und Sichtbarkeitsbereich gelten für die ganze Gruppe. QGIS kennt sie nur, wenn die Gruppe *als Gruppe dargestellt* wird; die erste Änderung schaltet das ein (Knopf **Als Gruppe darstellen**, ausschalten nimmt die Einstellungen der Gruppe zurück). **Exklusiv** lässt immer nur einen Layer der Gruppe sichtbar; die Layerliste zeigt dann Kreise statt Haken. **Auf Gruppe zoomen** zeigt alle ihre Layer.

**Daten** eines Vektorlayers oder einer Tabelle: Die Gruppe **Felder** legt Felder an (**Feld hinzufügen**: Name, Typ, Länge, Genauigkeit, Alias, Kommentar), **löscht** und **benennt** sie **um**; dazu der **Feldrechner**. Im Bearbeitungsmodus landet die Änderung im Bearbeitungspuffer und lässt sich rückgängig machen, sonst wird sie nach einer Rückfrage direkt in die Datenquelle geschrieben. Kann die Datenquelle keine Felder ändern, sind die Knöpfe ausgegraut. **Felder** unter Datenentwurf öffnet die Feldliste der Layereigenschaften.

**Beschriftung** eines Vektorlayers: **Beschriften** schaltet die Beschriftung ein. Ein Linienlayer bekommt dabei die Platzierung *Parallel*, weil QGIS Linien mit *Um Punkt* nicht beschriftet. Ein Layer kann mehrere **Beschriftungsklassen** haben, jede für eigene Objekte mit eigenem Text und Stil. Die Klasse wählt die Liste; die Knöpfe daneben legen eine **neue Klasse** an (Kopie der gewählten) oder **löschen** die gewählte. **Filter** legt fest, welche Objekte eine Klasse beschriftet, **Klasse beschriften** schaltet sie ein oder aus, und **Feld** wählt das Feld für den Text; sein Knopf ε öffnet den Ausdruckseditor für einen Text aus mehreren Feldern.

Befehle, die gerade nicht anwendbar sind (zum Beispiel *Auswahl aufheben* ohne Auswahl), sind ausgegraut.

## Buttons, Menüs und Galerien

- **Große, mittlere und kleine Buttons** führen einen Befehl aus. Buttons, die etwas ein- oder ausschalten (zum Beispiel ein Kartenwerkzeug), bleiben hervorgehoben, solange sie aktiv sind.
- **Split-Buttons** haben zwei Teile: Der obere oder linke Teil führt den Hauptbefehl aus, der Pfeil ▾ öffnet verwandte Befehle.
- **Menüs** (Beschriftung mit ▾) öffnen eine Liste von Befehlen.
- **Galerien** zeigen eine Auswahl von Werkzeugen oder Stilen (zum Beispiel die Geoverarbeitungswerkzeuge im Tab Analyse). Der Pfeil an der Seite zeigt alle Einträge. Welche Einträge erscheinen, lässt sich ändern, siehe [Ribbon anpassen](customize.md).
- **Steuerelemente** wie Felder für Maßstab, Deckkraft oder Schrift wirken direkt auf den aktiven Layer.
- **Dialog-Launcher:** Der kleine Pfeil ↘ rechts unten in einer Gruppe öffnet den passenden QGIS-Dialog mit weiteren Einstellungen.
- **Tooltips** zeigen Name, Beschreibung und Tastenkürzel eines Befehls.

Ist das Fenster schmal, klappen Gruppen von rechts zu einem einzelnen Button zusammen. Ein Klick darauf zeigt die Gruppe als Ausklappliste.

## Schnellzugriffsleiste

Die kleinen Icons links in der Kopfzeile bilden die **Schnellzugriffsleiste**. Ihre Befehle sind in jedem Tab erreichbar.

![Menü der Schnellzugriffsleiste](../images/de/quick_access_menu.png)

- **Befehl hinzufügen:** Rechtsklick auf einen Befehl im Ribbon, dann **Zur Schnellzugriffsleiste hinzufügen**.
- **Befehl entfernen:** im Menü ▾ das Häkchen entfernen, oder Rechtsklick darauf und **Aus Schnellzugriffsleiste entfernen**.
- **Reihenfolge:** im Editor, siehe [Ribbon anpassen](customize.md).
- **Standard wiederherstellen** im Menü ▾ stellt die gelieferten Befehle wieder her.

Das Menü ▾ enthält außerdem die Einstellungen des Ribbons: Kürzel, Minimieren, Editor, Anordnungen, Darstellung, klassische QGIS-Oberfläche und diese Anleitung. Dieselben Einträge stehen im Rechtsklick-Menü des Ribbons:

![Rechtsklick-Menü des Ribbons](../images/de/context_menu.png)

## Ribbon minimieren

Das Ribbon lässt sich auf seine Kopfzeile verkleinern, damit die Karte mehr Platz hat:

- Knopf **^** rechts in der Kopfzeile,
- **Strg+F1**,
- Doppelklick auf einen Tab,
- **Ribbon minimieren** im Menü ▾ oder im Rechtsklick-Menü.

![Minimiertes Ribbon](../images/de/minimized.png)

Im minimierten Zustand zeigt ein Klick auf einen Tab das Ribbon über der Karte. Ein Klick daneben schließt es wieder. Dauerhaft zeigt man es mit dem Knopf zum Anheften, mit Strg+F1 oder mit einem erneuten Doppelklick auf einen Tab. Der Zustand bleibt für den nächsten Start erhalten.

## Befehlssuche

Das Suchfeld rechts in der Kopfzeile findet Befehle nach Name oder Beschreibung, siehe [Tastatur: Kürzel und Suche](keyboard.md).
