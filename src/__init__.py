# Package bootstrap: install deterministic unique photo-cover recipes before
# render.py / reel_scenes.py import src.theme.
from . import theme as _theme
from .cover_variants import install as _install_cover_variants

_install_cover_variants(_theme)
