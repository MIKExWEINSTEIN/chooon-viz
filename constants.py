"""
constants.py - Shared constants for chooon-viz.

Kept in a separate module with NO native/pygame imports so that the tkinter
control-panel subprocess can import these without loading SDL or any other
GUI framework that might claim NSApplication on macOS.
"""

PALETTE_NAMES = [
    "Rainbow",
    "Inferno",
    "Ocean",
    "Neon",
    "Forest",
    "Sunset",
]

SYMMETRY_MODES = [
    "None",           # original image
    "Mirror H",       # left half reflected right  (vertical axis)
    "Mirror V",       # top half reflected down    (horizontal axis)
    "4-Way",          # top-left quadrant × 4
    "Kaleidoscope 4", # 4-segment polar kaleidoscope
    "Kaleidoscope 8", # 8-segment polar kaleidoscope (classic)
]
