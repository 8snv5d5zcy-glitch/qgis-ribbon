"""Schnellzugriffsleiste: Standard aus der Ribbon-Definition, Anpassungen des Nutzers.

Gespeichert wird die vollständige Liste der Befehls-IDs als Text mit Kommas
(``None`` = keine Anpassung, Standard gilt; ``""`` = bewusst leer). So bleibt
die Reihenfolge erhalten, und ein geänderter Standard in der Definition
wirkt, solange der Nutzer nichts angepasst hat. Unbekannte IDs (z. B. nach
einer Änderung der Definition) werden still übergangen.

Nur Buttons können in die Leiste (keine Steuerelemente oder Galerien).
"""


def allowed(command):
    return command.kind == "button" and command.gallery is None


def effective(ribbon, stored):
    """Befehle der Leiste: gespeicherte Anpassung oder Standard aus der Definition."""
    if stored is None:
        return tuple(ribbon.quick_access)
    out = []
    for cid in parse(stored):
        cmd = ribbon.commands.get(cid)
        if cmd is not None and allowed(cmd) and cmd not in out:
            out.append(cmd)
    return tuple(out)


def parse(stored):
    return [c.strip() for c in (stored or "").split(",") if c.strip()]


def serialize(commands):
    return ",".join(c.id for c in commands)


def added(current, command):
    """Liste mit ``command`` am Ende (unverändert, wenn schon enthalten oder nicht erlaubt)."""
    if command in current or not allowed(command):
        return tuple(current)
    return tuple(current) + (command,)


def removed(current, command):
    return tuple(c for c in current if c is not command and c.id != command.id)
