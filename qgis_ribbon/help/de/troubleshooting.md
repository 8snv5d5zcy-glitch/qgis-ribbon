# Einstellungen, Zurücksetzen und Probleme

[Inhalt](index.md)

## Wo die Einstellungen liegen

Alle Einstellungen des Ribbons stehen im QGIS-Benutzerprofil unter dem Schlüssel `qgis_ribbon`: aktuelle Anordnung, gespeicherte Anordnungen, Darstellung, minimierter Zustand, Schnellzugriff und Kürzel. Ein anderes Profil startet mit dem Standard-Ribbon.

In Projekten wird nichts gespeichert. Nur Domänen von Layern ohne passende Datenquelle liegen im Projekt (siehe [Weitere Werkzeuge](tools.md)).

## Zurücksetzen

| Was | Wie |
|---|---|
| Tabs, Gruppen, Galerien, Schnellzugriff, Kürzel | **Anordnungen › Standardanordnung** |
| Tabs, Gruppen und Schnellzugriff im Editor | **Standard wiederherstellen** im Editor (rückgängig machbar) |
| eine einzelne Gruppe | Menü ⋯ der Gruppe im Editor |
| nur Schnellzugriff | **Standard wiederherstellen** im Menü ▾ |
| nur Kürzel | **Alle zurücksetzen** in Kürzel anpassen |
| alles | die Gruppe `qgis_ribbon` in **Einstellungen › Optionen › Erweitert** (Editor für erweiterte Einstellungen) löschen und QGIS neu starten |

Wer die eigene Anordnung später zurückhaben möchte, sichert sie vorher mit **Anordnungen › Exportieren …**.

## Häufige Fragen

**Das Ribbon ist weg, die Werkzeugleisten von QGIS sind zurück.**
Die klassische QGIS-Oberfläche ist aktiv. **Ansicht › Ribbon-Oberfläche** wählen.

**Ein Befehl ist ausgegraut.**
Er braucht einen passenden aktiven Layer (zum Beispiel einen Vektorlayer oder einen Layer im Bearbeitungsmodus), eine Auswahl oder ein Plugin, das nicht geladen ist. Bei fehlenden Befehlen nennt der Tooltip den Grund.

**Das Ribbon zeigt englische Texte (oder deutsche).**
Das Ribbon folgt der Sprache von QGIS. Sie lässt sich unter **Einstellungen › Optionen › Allgemein** ändern; danach QGIS neu starten.

**Werkzeugleisten eines Plugins fehlen.**
Solange das Ribbon aktiv ist, sind Plugin-Leisten ausgeblendet. Ihre Befehle stehen im Tab [Erweiterungen](extensions.md).

**Alt zeigt keine Kürzel.**
Alt allein drücken und loslassen, ohne andere Taste, während das Hauptfenster von QGIS aktiv ist. Alt mit einem Buchstaben öffnet die Menüs von QGIS.

## Deinstallieren

**Erweiterungen › Erweiterungen verwalten und installieren …** deaktiviert oder deinstalliert QGIS Ribbon. QGIS zeigt dann wieder seine Werkzeugleisten und die vorherige Fensteraufteilung. Die Einstellungen unter `qgis_ribbon` bleiben im Profil; bei Bedarf wie oben beschrieben löschen.

## Probleme melden

Fehler und Vorschläge bitte im [Issue-Tracker](https://github.com/8snv5d5zcy-glitch/qgis-ribbon/issues) melden. Hilfreich sind QGIS-Version, Betriebssystem, die Schritte bis zum Fehler und Meldungen aus dem Bedienfeld Protokollmeldungen (Reiter *QGIS Ribbon*).
