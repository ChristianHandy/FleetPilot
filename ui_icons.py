"""
ui_icons.py — Inline SVG line icons for templates.

Registered as the Jinja global ``icon(name, size=16)``. Icons are 24x24
stroke paths drawn with ``currentColor`` so they inherit text colour.
"""
from markupsafe import Markup

_PATHS = {
    "home":        '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M10 21v-6h4v6"/>',
    "server":      '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
    "list":        '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "search":      '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "refresh":     '<path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/>',
    "arrow-up":    '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "arrow-down":  '<path d="M12 5v14M19 12l-7 7-7-7"/>',
    "cpu":         '<rect x="5" y="5" width="14" height="14" rx="1.5"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "activity":    '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "hard-drive":  '<path d="M22 12H2"/><path d="M5.5 5h13L22 12v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-6z"/><path d="M6 15.5h.01M10 15.5h.01"/>',
    "fan":         '<circle cx="12" cy="12" r="2"/><path d="M12 10c0-4 1-7 4-7 2.5 0 3 3 0 5l-2.3 2.6"/><path d="M14 12c4 0 7 1 7 4 0 2.5-3 3-5 0l-2.6-2.3"/><path d="M12 14c0 4-1 7-4 7-2.5 0-3-3 0-5l2.3-2.6"/><path d="M10 12c-4 0-7-1-7-4 0-2.5 3-3 5 0l2.6 2.3"/>',
    "monitor":     '<rect x="2" y="3" width="20" height="14" rx="1.5"/><path d="M8 21h8M12 17v4"/>',
    "laptop":      '<rect x="4" y="4" width="16" height="11" rx="1.5"/><path d="M2 19h20"/>',
    "database":    '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "shield":      '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
    "moon":        '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "sun":         '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "check":       '<path d="M20 6 9 17l-5-5"/>',
    "check-circle":'<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "x-circle":    '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    "thermometer": '<path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/>',
    "download":    '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 21h16"/>',
    "settings":    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "mail":        '<rect x="3" y="5" width="18" height="14" rx="1.5"/><path d="m3 7 9 6 9-6"/>',
    "globe":       '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "users":       '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>',
    "user":        '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "puzzle":      '<path d="M10 4a2 2 0 1 1 4 0v2h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H6v-4H4a2 2 0 1 1 0-4h2V6h4z"/>',
    "file-text":   '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    "clipboard":   '<rect x="5" y="4" width="14" height="17" rx="1.5"/><path d="M9 4V3h6v1M9 10h6M9 14h6"/>',
    "lock":        '<rect x="4" y="10" width="16" height="11" rx="1.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "key":         '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.3-9.3M16 7l3 3M18 5l2 2"/>',
    "smartphone":  '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
    "alert":       '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "zap":         '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    "trash":       '<path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"/>',
    "pencil":      '<path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    "power":       '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
    "network":     '<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-5h14v5"/>',
    "inbox":       '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13L22 12v6a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-6z"/>',
    "plug":        '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
    "disc":        '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2"/>',
    "link":        '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    "tag":         '<path d="M3 3h8l10 10-8 8L3 11z"/><path d="M7.5 7.5h.01"/>',
    "map-pin":     '<path d="M12 22s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>',
    "radio":       '<path d="M5 12a7 7 0 0 1 14 0M8.5 12a3.5 3.5 0 0 1 7 0"/><circle cx="12" cy="12" r="1"/><path d="M12 13v8"/>',
    "play":        '<path d="M6 4v16l14-8z"/>',
    "chart":       '<path d="M3 3v18h18"/><path d="M7 15v3M12 9v9M17 12v6"/>',
    "cloud":       '<path d="M7 18a5 5 0 1 1 1-9.9A6 6 0 0 1 19.5 10 4 4 0 0 1 18 18z"/>',
    "plane":       '<path d="M21 15.5 13.5 11V5a1.5 1.5 0 0 0-3 0v6L3 15.5v2l7.5-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5l-2-1.5v-4l7.5 2.5z"/>',
    "scroll":      '<path d="M6 3h11a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7"/><path d="M6 3a2 2 0 0 0-2 2v2h4"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "plus":        '<path d="M12 5v14M5 12h14"/>',
    "clock":       '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "layers":      '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "accessibility": '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="7" r="1.25" fill="currentColor"/><path d="M7.5 10.5 12 11.5l4.5-1M12 11.5V15m0 0-2.5 4.5M12 15l2.5 4.5"/>',
    "dot":         '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
}

# Emoji found in the legacy templates, mapped to the icon that replaces them.
EMOJI_TO_ICON = {
    "🏠": "home", "🖧": "network", "📝": "list", "🔍": "search", "🔎": "search",
    "🔄": "refresh", "⬆": "arrow-up", "⬇": "arrow-down", "🖥": "monitor",
    "💻": "laptop", "📊": "chart", "📈": "chart", "💾": "hard-drive",
    "💿": "disc", "🌬": "fan", "🌀": "fan", "💨": "fan", "🗄": "database",
    "🛡": "shield", "🌙": "moon", "☀": "sun", "✅": "check-circle",
    "❌": "x-circle", "🌡": "thermometer", "🚀": "download", "⚙": "settings",
    "✉": "mail", "📧": "mail", "🌐": "globe", "👥": "users", "👤": "user",
    "🧩": "puzzle", "📜": "scroll", "📋": "clipboard", "🔐": "lock",
    "🔒": "lock", "🔑": "key", "🗝": "key", "📱": "smartphone", "⚠": "alert",
    "⚡": "zap", "🗑": "trash", "✏": "pencil", "⏻": "power", "📭": "inbox",
    "🧠": "cpu", "🔌": "plug", "🎮": "cpu", "🔗": "link", "🏷": "tag",
    "📍": "map-pin", "📡": "radio", "▶": "play", "☁": "cloud", "🛩": "plane",
    "🛫": "plane", "🧰": "cpu", "📶": "activity", "➕": "plus", "⏱": "clock",
    "🕐": "clock", "📦": "layers", "🔴": "dot", "🟢": "dot", "🟡": "dot",
}


def icon(name, size=16, cls=""):
    body = _PATHS.get(name)
    if body is None:
        return Markup("")
    klass = "icon" + (f" {cls}" if cls else "")
    return Markup(
        f'<svg class="{klass}" width="{int(size)}" height="{int(size)}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


def register(app):
    """Expose ``icon()`` and ``asset_version()`` to every template of ``app``."""
    import os

    def asset_version(name):
        try:
            return int(os.path.getmtime(os.path.join(app.static_folder, name)))
        except OSError:
            return 0

    app.jinja_env.globals["icon"] = icon
    app.jinja_env.globals["asset_version"] = asset_version
