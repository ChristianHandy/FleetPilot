"""
easy_language.py — plain-language texts for the "Easy language" setting.

When a user turns on easy language (Accessibility settings), FleetPilot uses
simpler menu names and shows a short explanation at the top of each page.
The texts follow easy-to-read rules: short sentences, one idea per sentence,
active voice, and hard words explained the first time they appear.

English and German are written out; other interface languages use English.
"""

# Simpler names for the sidebar. Keys are the normal English labels.
NAV = {
    "en": {
        "Home": "Start page",
        "Manage Hosts": "My computers",
        "Network Scanner": "Find computers",
        "Update Dashboard": "Updates",
        "Server update": "Update this server",
        "Hardware overview": "Computer parts",
        "SMART health": "Disk health",
        "Storage & disks": "Disks",
        "Fans & cooling": "Fans",
        "VM controllers": "Virtual computers",
        "Storage controllers": "Storage systems",
        "Backup servers": "Backups of computers",
        "Scheduled shutdown": "Turn off on a timer",
        "CheckMK": "Monitoring link",
        "System monitor": "This server's load",
        "FleetPilot update": "Update FleetPilot",
        "Update Settings": "Update times",
        "Email Config": "Email",
        "Proxy services": "Web addresses",
        "Production status": "Safety check",
        "Audit trail": "Activity list",
        "Security center": "Safety settings",
        "Notifications": "Messages to my phone",
        "Sign-in & security": "My logins",
        "Backups": "Save FleetPilot data",
        "Plugins": "Add-ons",
        "My Profile": "My account",
        "User Management": "People",
        "Accessibility": "Accessibility",
        "Servers": "Computers",
        "Hardware": "Parts",
        "Virtualization": "Virtual computers",
        "Operations": "Daily tasks",
        "System": "Settings",
        "Account": "My account",
    },
    "de": {
        "Home": "Startseite",
        "Manage Hosts": "Meine Computer",
        "Network Scanner": "Computer finden",
        "Update Dashboard": "Updates",
        "Server update": "Diesen Server aktualisieren",
        "Hardware overview": "Teile im Computer",
        "SMART health": "Zustand der Festplatten",
        "Storage & disks": "Festplatten",
        "Fans & cooling": "Lüfter",
        "VM controllers": "Virtuelle Computer",
        "Storage controllers": "Speicher-Systeme",
        "Backup servers": "Sicherungen",
        "Scheduled shutdown": "Zeitschaltung zum Ausschalten",
        "CheckMK": "Verbindung zu CheckMK",
        "System monitor": "Auslastung von diesem Server",
        "FleetPilot update": "FleetPilot aktualisieren",
        "Update Settings": "Zeiten für Updates",
        "Email Config": "E-Mail",
        "Proxy services": "Web-Adressen",
        "Production status": "Sicherheits-Prüfung",
        "Audit trail": "Liste der Aktionen",
        "Security center": "Sicherheit",
        "Notifications": "Nachrichten aufs Handy",
        "Sign-in & security": "Meine Anmeldungen",
        "Backups": "FleetPilot-Daten sichern",
        "Plugins": "Erweiterungen",
        "My Profile": "Mein Konto",
        "User Management": "Personen",
        "Accessibility": "Barrierefreiheit",
        "Servers": "Computer",
        "Hardware": "Teile",
        "Virtualization": "Virtuelle Computer",
        "Operations": "Tägliche Aufgaben",
        "System": "Einstellungen",
        "Account": "Mein Konto",
    },
}

# Short explanations per page, matched by URL path prefix (longest wins).
PAGES = {
    "en": {
        "/index": "This is the start page. You see your computers and services here. Green means: everything is fine. Red means: something needs help.",
        "/hosts": "Here you see all computers that FleetPilot looks after. FleetPilot calls them hosts. You can add a computer. You can update a computer. You can turn a computer on or off.",
        "/scanner": "This page looks for computers in your network. A network is the connection between your computers. Press Start scan. FleetPilot then shows the computers it finds. You can add a found computer to FleetPilot.",
        "/dashboard": "Here you install updates. An update is new software that fixes problems. You can update one computer. You can also turn on automatic updates.",
        "/server_update": "Here you update the computer that runs FleetPilot. This can take a few minutes. Only administrators can do this.",
        "/hw_overview": "Here you see the parts inside your computers. For example the processor, the memory and the disks. Press Refresh all to load new data.",
        "/smart": "Here you see how healthy your disks are. A disk stores your files. SMART is a self-check that every disk does. Good means: the disk is fine. Warning or Failed means: copy your files to a safe place soon.",
        "/storage/workspace": "Here you see all disks in one place. You can check a disk. You can also erase a disk. Erasing deletes everything on the disk. FleetPilot asks you before it erases.",
        "/disks": "Here you work with the disks in this computer. You can check a disk. You can erase and prepare a disk. Erasing deletes everything on the disk.",
        "/fans": "Here you control fans. Fans cool your computers. You can see how fast each fan turns. You can make a fan faster or slower.",
        "/commander": "Here you control a Corsair Commander. That is a small box that controls fans in a computer.",
        "/vm": "Here you manage virtual computers. A virtual computer runs inside another computer. You can start and stop virtual computers.",
        "/storage": "Here you manage storage systems. A storage system is a computer that keeps many disks. For example TrueNAS or Unraid.",
        "/backup": "Here you see your backups. A backup is a copy of your data. If something breaks, you can get your data back from the copy.",
        "/shutdown_schedule": "Here you turn computers off at a set time. For example every night at 11 pm. This saves power.",
        "/checkmk": "Here you connect FleetPilot to CheckMK. CheckMK is another program that watches computers.",
        "/monitor": "Here you see how busy this server is. CPU is how hard the computer works. RAM is the short-term memory. High numbers mean the computer is very busy.",
        "/hw": "Here you test computers under heavy load. This is called a stress test. It shows if a computer stays stable when it works very hard.",
        "/fleetpilot_update": "Here you update FleetPilot itself. Your data stays safe during the update.",
        "/update_settings": "Here you choose when updates happen automatically. For example every Sunday at night.",
        "/email_settings": "Here you set up email. FleetPilot can then send you a message when something goes wrong.",
        "/system/proxy": "Here you manage web addresses. A web address lets people open a service in the browser.",
        "/system/production": "This page checks if FleetPilot is set up safely. Each box shows one check.",
        "/system/audit": "This is a list of what people did in FleetPilot. For example who logged in or who changed a setting.",
        "/system/backups": "Here you save all FleetPilot data in one file. Keep the file in a safe place. You can use the file later to get everything back.",
        "/plugins": "Here you add extra functions to FleetPilot. These are called plugins or add-ons. Only install add-ons that you trust.",
        "/users/profile": "This is your account. You can change your email address. You can change your password.",
        "/system/security": "Here you check if FleetPilot is safe. Green means good. Red means: please fix this. You can also choose who may log in from where.",
        "/system/notifications": "Here FleetPilot learns where to send messages. For example to your phone or to a chat. FleetPilot sends a message when a disk is ill or when someone tries wrong passwords.",
        "/users/security": "Here you see where you are logged in. You can log out other devices. You can also make a key for programs. A program uses the key instead of your password.",
        "/reauth": "Please type your password again. This keeps important settings safe.",
        "/users/accessibility": "Here you make FleetPilot easier to use. You can make the text bigger. You can make colors stronger. You can turn on easy language.",
        "/users": "Here you manage the people who can use FleetPilot. Each person has a role. Viewers can only look. Operators can do tasks. Administrators can change everything.",
        "/2fa": "Here you protect your account with a second step. After your password, FleetPilot also asks for a code from your phone or a security key.",
    },
    "de": {
        "/index": "Das ist die Startseite. Hier sehen Sie Ihre Computer und Dienste. Grün bedeutet: alles ist gut. Rot bedeutet: etwas braucht Hilfe.",
        "/hosts": "Hier sehen Sie alle Computer, die FleetPilot betreut. FleetPilot nennt sie Hosts. Sie können einen Computer hinzufügen. Sie können einen Computer aktualisieren. Sie können einen Computer ein- oder ausschalten.",
        "/scanner": "Diese Seite sucht Computer in Ihrem Netzwerk. Das Netzwerk ist die Verbindung zwischen Ihren Computern. Drücken Sie auf Suche starten. Dann zeigt FleetPilot die gefundenen Computer. Sie können einen gefundenen Computer zu FleetPilot hinzufügen.",
        "/dashboard": "Hier installieren Sie Updates. Ein Update ist neue Software. Sie behebt Fehler. Sie können einen Computer aktualisieren. Sie können auch automatische Updates einschalten.",
        "/server_update": "Hier aktualisieren Sie den Computer, auf dem FleetPilot läuft. Das kann ein paar Minuten dauern. Nur Administratoren dürfen das.",
        "/hw_overview": "Hier sehen Sie die Teile in Ihren Computern. Zum Beispiel den Prozessor, den Speicher und die Festplatten. Drücken Sie auf Alle aktualisieren für neue Daten.",
        "/smart": "Hier sehen Sie, wie gesund Ihre Festplatten sind. Eine Festplatte speichert Ihre Dateien. SMART ist ein Selbst-Test von jeder Festplatte. Gut bedeutet: die Festplatte ist in Ordnung. Warnung oder Fehler bedeutet: Kopieren Sie Ihre Dateien bald an einen sicheren Ort.",
        "/storage/workspace": "Hier sehen Sie alle Festplatten an einem Ort. Sie können eine Festplatte prüfen. Sie können eine Festplatte auch löschen. Löschen entfernt alles auf der Festplatte. FleetPilot fragt vorher nach.",
        "/disks": "Hier arbeiten Sie mit den Festplatten in diesem Computer. Sie können eine Festplatte prüfen. Sie können eine Festplatte löschen und vorbereiten. Löschen entfernt alles auf der Festplatte.",
        "/fans": "Hier steuern Sie Lüfter. Lüfter kühlen Ihre Computer. Sie sehen, wie schnell jeder Lüfter dreht. Sie können einen Lüfter schneller oder langsamer machen.",
        "/commander": "Hier steuern Sie einen Corsair Commander. Das ist ein kleines Gerät. Es steuert die Lüfter in einem Computer.",
        "/vm": "Hier verwalten Sie virtuelle Computer. Ein virtueller Computer läuft in einem anderen Computer. Sie können virtuelle Computer starten und stoppen.",
        "/storage": "Hier verwalten Sie Speicher-Systeme. Ein Speicher-System ist ein Computer mit vielen Festplatten. Zum Beispiel TrueNAS oder Unraid.",
        "/backup": "Hier sehen Sie Ihre Sicherungen. Eine Sicherung ist eine Kopie von Ihren Daten. Wenn etwas kaputt geht, holen Sie Ihre Daten aus der Kopie zurück.",
        "/shutdown_schedule": "Hier schalten Sie Computer zu einer festen Zeit aus. Zum Beispiel jede Nacht um 23 Uhr. Das spart Strom.",
        "/checkmk": "Hier verbinden Sie FleetPilot mit CheckMK. CheckMK ist ein anderes Programm. Es beobachtet Computer.",
        "/monitor": "Hier sehen Sie, wie stark dieser Server arbeitet. CPU bedeutet: wie viel der Computer rechnet. RAM ist der Arbeits-Speicher. Hohe Zahlen bedeuten: der Computer ist sehr beschäftigt.",
        "/hw": "Hier testen Sie Computer unter starker Last. Das heißt Belastungs-Test. Der Test zeigt, ob ein Computer stabil bleibt.",
        "/fleetpilot_update": "Hier aktualisieren Sie FleetPilot selbst. Ihre Daten bleiben beim Update sicher.",
        "/update_settings": "Hier wählen Sie, wann Updates von selbst laufen. Zum Beispiel jeden Sonntag in der Nacht.",
        "/email_settings": "Hier richten Sie E-Mail ein. Dann schickt FleetPilot Ihnen eine Nachricht, wenn etwas nicht stimmt.",
        "/system/proxy": "Hier verwalten Sie Web-Adressen. Mit einer Web-Adresse öffnet man einen Dienst im Browser.",
        "/system/production": "Diese Seite prüft, ob FleetPilot sicher eingerichtet ist. Jedes Feld zeigt eine Prüfung.",
        "/system/audit": "Das ist eine Liste von dem, was Personen in FleetPilot getan haben. Zum Beispiel: Wer hat sich angemeldet? Wer hat eine Einstellung geändert?",
        "/system/backups": "Hier speichern Sie alle FleetPilot-Daten in einer Datei. Bewahren Sie die Datei sicher auf. Mit der Datei holen Sie später alles zurück.",
        "/plugins": "Hier fügen Sie FleetPilot neue Funktionen hinzu. Diese heißen Erweiterungen oder Plugins. Installieren Sie nur Erweiterungen, denen Sie vertrauen.",
        "/users/profile": "Das ist Ihr Konto. Sie können Ihre E-Mail-Adresse ändern. Sie können Ihr Passwort ändern.",
        "/system/security": "Hier prüfen Sie, ob FleetPilot sicher ist. Grün heißt: gut. Rot heißt: Bitte ändern. Sie können auch festlegen, von wo man sich anmelden darf.",
        "/system/notifications": "Hier sagen Sie FleetPilot, wohin es Nachrichten schicken soll. Zum Beispiel auf Ihr Handy oder in einen Chat. FleetPilot schickt eine Nachricht, wenn eine Festplatte krank ist. Oder wenn jemand falsche Passwörter eingibt.",
        "/users/security": "Hier sehen Sie, wo Sie angemeldet sind. Sie können andere Geräte abmelden. Sie können auch einen Schlüssel für Programme machen. Ein Programm benutzt den Schlüssel statt Ihrem Passwort.",
        "/reauth": "Bitte geben Sie Ihr Passwort noch einmal ein. So bleiben wichtige Einstellungen sicher.",
        "/users/accessibility": "Hier machen Sie FleetPilot leichter zu benutzen. Sie können die Schrift größer machen. Sie können die Farben stärker machen. Sie können Leichte Sprache einschalten.",
        "/users": "Hier verwalten Sie die Personen, die FleetPilot benutzen. Jede Person hat eine Rolle. Betrachter dürfen nur ansehen. Operatoren dürfen Aufgaben ausführen. Administratoren dürfen alles ändern.",
        "/2fa": "Hier schützen Sie Ihr Konto mit einem zweiten Schritt. Nach dem Passwort fragt FleetPilot nach einem Code von Ihrem Handy oder einem Sicherheits-Schlüssel.",
    },
}

HELP_HEADING = {"en": "In simple words", "de": "In Leichter Sprache"}


def _lang(lang):
    return lang if lang in NAV else "en"


def nav_label(label, lang):
    """Return the easy-language name for a sidebar label, or the label itself."""
    return NAV[_lang(lang)].get(str(label), label)


def page_help(path, lang):
    """Return the easy-language explanation for the page at ``path``, or None."""
    pages = PAGES[_lang(lang)]
    if path in ("/", ""):
        path = "/index"
    best = None
    for prefix in pages:
        if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
            if best is None or len(prefix) > len(best):
                best = prefix
    return pages.get(best) if best else None


def help_heading(lang):
    return HELP_HEADING[_lang(lang)]
