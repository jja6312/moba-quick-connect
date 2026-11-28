"""Application-wide colors with persistent preset and custom accents."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

PRESETS = (
    ('purple', '보라', '#a475fb'), ('blue', '블루', '#5c9dff'),
    ('teal', '민트', '#42ccb5'), ('amber', '앰버', '#edb553'),
    ('rose', '로즈', '#ec83aa'), ('slate', '그레이', '#9aa8bd'),
    ('light', '라이트', '#8055c8'), ('custom', '사용자 색', None),
)


def mix(left, right, ratio):
    a, b = QColor(left), QColor(right)
    return QColor.fromRgbF(*(a.getRgbF()[i] * (1 - ratio) + b.getRgbF()[i] * ratio for i in range(3))).name()


def colors(theme='purple', custom='#a475fb'):
    preset = next((p for p in PRESETS if p[0] == theme), PRESETS[0])
    accent = preset[2] or (custom if QColor(custom).isValid() else '#a475fb')
    light = theme == 'light'
    window = '#f4f5f9' if light else mix('#171b23', accent, .045)
    card = '#ffffff' if light else mix('#242733', accent, .035)
    base = '#ffffff' if light else '#151820'
    text = '#232531' if light else '#eeeff6'
    muted = '#626a7c' if light else '#a8b0c3'
    border = '#d6dae5' if light else '#3c4252'
    selected = mix(card, accent, .24 if light else .36)
    jump = mix(card, accent, .08 if light else .12)
    a = QColor(accent)
    brightness = .299 * a.redF() + .587 * a.greenF() + .114 * a.blueF()
    button_text = '#151820' if brightness > .55 else '#ffffff'
    mapping = {}
    for old in ('#1c1b29', '#191824', '#1d1b29', '#16151f'):
        mapping[old] = window
    for old in ('#232132', '#23202f', '#262235', '#262132', '#2a2439'):
        mapping[old] = card
    for old in ('#171621', '#1c192b', '#171220', '#171024', '#1d1b28'):
        mapping[old] = base
    for old in ('#343143', '#363345', '#3b374e', '#403650', '#3d344d', '#373142', '#494059', '#3b314a', '#42354f', '#312a40', '#4b3d5b'):
        mapping[old] = border
    for old in ('#a475fb', '#aa7aff', '#b68aff', '#ba91ff', '#b296ff'):
        mapping[old] = accent
    for old in ('#b28bff', '#b0a0e5', '#bca4e8', '#b9a0df', '#c9adff', '#d0b3ff', '#cfb9ec'):
        mapping[old] = mix(accent, text, .30)
    for old in ('#eeecf7', '#faf4ff', '#e9dcff'):
        mapping[old] = text
    for old in ('#a7a2bd', '#a8a1ba', '#b6b0ca', '#bfb1d4', '#b6a8d4', '#beb6d3', '#8f7da9', '#9780b6', '#b9afd0'):
        mapping[old] = muted
    for old in ('#493367', '#483263', '#493667', '#39304f', '#44305e', '#49375f', '#302641'):
        mapping[old] = selected
    for old in ('#2b233a', '#2b263f', '#2e273f', '#282235', '#382f4e', '#30263e'):
        mapping[old] = jump
    mapping['#ffb1c8'] = '#b62749' if light else '#ffb1c8'
    return {'mapping': mapping, 'window': window, 'card': card, 'base': base, 'text': text,
            'muted': muted, 'accent': accent, 'button_text': button_text, 'border': border,
            'selected': selected, 'jump': jump, 'light': light}


def apply(app, stylesheet, theme='purple', custom='#a475fb'):
    tokens = colors(theme, custom)
    import re
    stylesheet = re.sub(r'#[0-9a-fA-F]{6}', lambda m: tokens['mapping'].get(m[0].lower(), m[0]), stylesheet)
    stylesheet += f'\nQPushButton#primary {{color:{tokens["button_text"]};background:{tokens["accent"]};}}'
    palette = QPalette()
    for role, value in ((QPalette.ColorRole.Window, tokens['window']), (QPalette.ColorRole.WindowText, tokens['text']),
                        (QPalette.ColorRole.Base, tokens['base']), (QPalette.ColorRole.AlternateBase, tokens['jump']),
                        (QPalette.ColorRole.Text, tokens['text']), (QPalette.ColorRole.Button, tokens['card']),
                        (QPalette.ColorRole.ButtonText, tokens['text']), (QPalette.ColorRole.Highlight, tokens['selected']),
                        (QPalette.ColorRole.HighlightedText, tokens['text'])):
        palette.setColor(role, QColor(value))
    app.setProperty('mobaTheme', tokens)
    app.setPalette(palette)
    app.setStyleSheet(stylesheet)
    return tokens


def color(widget, legacy):
    while widget is not None and not hasattr(widget, 'window'):
        widget = widget.parent()
    tokens = widget.window().property('mobaTheme') if widget else None
    tokens = tokens or (QApplication.instance().property('mobaTheme') if QApplication.instance() else None)
    return QColor(tokens['mapping'].get(legacy.lower(), legacy) if tokens else legacy)
