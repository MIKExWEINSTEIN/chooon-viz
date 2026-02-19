"""
controls.py - Tkinter control panel for chooon-viz.

Runs in its own thread and communicates with the main renderer via a shared
`params` dict and an `events` queue.  The panel stays on top of other windows
but does not block the pygame render loop.
"""

from __future__ import annotations
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Optional

from visuals import PALETTE_NAMES


# Events the panel can emit
EVT_LOAD_IMAGE   = "load_image"
EVT_CLEAR_IMAGE  = "clear_image"
EVT_QUIT         = "quit"
EVT_TOGGLE       = "toggle"   # payload = layer name


class ControlPanel:
    """
    Tkinter GUI panel that lives in a dedicated thread.

    ``params`` is a plain dict shared between this thread and the render
    thread.  Writes from tkinter callbacks are atomic on CPython (GIL) for
    simple types, which is sufficient here.

    ``events`` is a thread-safe queue the main thread should drain each frame.
    """

    def __init__(self, params: dict, events: queue.Queue):
        self.params = params
        self.events = events
        self._root: Optional[tk.Tk] = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="ControlPanel")

    def start(self):
        self._thread.start()

    def stop(self):
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass

    # ── internals ────────────────────────────────────────────────────────────

    def _run(self):
        self._root = tk.Tk()
        self._root.title("chooon-viz controls")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#1a1a2e")

        self._build_ui()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self):
        self.events.put({"type": EVT_QUIT})
        self._root.destroy()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = self._root
        BG   = "#1a1a2e"
        FG   = "#e0e0e0"
        ACC  = "#16213e"
        HL   = "#0f3460"
        SL   = "#e94560"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale",
                         background=BG, troughcolor=ACC,
                         sliderlength=18, sliderrelief="flat")
        style.configure("TLabel",  background=BG, foreground=FG)
        style.configure("TFrame",  background=BG)
        style.configure("TButton",
                         background=HL, foreground=FG,
                         relief="flat", padding=4)
        style.map("TButton", background=[("active", SL)])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox",
                         fieldbackground=ACC, background=ACC,
                         foreground=FG, selectbackground=HL)

        pad = dict(padx=10, pady=4)

        # ── Title ────────────────────────────────────────────────────────────
        tk.Label(root, text="chooon-viz", font=("Courier", 16, "bold"),
                 bg=BG, fg=SL).pack(**pad, pady=(12, 0))
        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Sliders ──────────────────────────────────────────────────────────
        frame_sliders = ttk.Frame(root)
        frame_sliders.pack(fill="x", **pad)

        self._add_slider(frame_sliders, "Speed",     "speed",
                         0.1, 4.0, self.params.get("speed", 1.0), row=0)
        self._add_slider(frame_sliders, "Intensity", "intensity",
                         0.0, 3.0, self.params.get("intensity", 1.0), row=1)

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Colour palette ───────────────────────────────────────────────────
        pal_frame = ttk.Frame(root)
        pal_frame.pack(fill="x", **pad)
        ttk.Label(pal_frame, text="Color Palette").grid(row=0, column=0, sticky="w")

        self._palette_var = tk.StringVar(value=self.params.get("palette", PALETTE_NAMES[0]))
        combo = ttk.Combobox(pal_frame, textvariable=self._palette_var,
                             values=PALETTE_NAMES, state="readonly", width=14)
        combo.grid(row=0, column=1, padx=(10, 0))
        combo.bind("<<ComboboxSelected>>", self._on_palette_change)

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Layer toggles ────────────────────────────────────────────────────
        tog_frame = ttk.Frame(root)
        tog_frame.pack(fill="x", **pad)
        ttk.Label(tog_frame, text="Layers", font=("Courier", 10, "bold")).pack(anchor="w")

        layers = [
            ("Plasma background", "show_plasma"),
            ("Waveform ring",     "show_waveform"),
            ("Particles",         "show_particles"),
            ("Spectrum bars",     "show_spectrum"),
        ]
        self._layer_vars: dict[str, tk.BooleanVar] = {}
        for label, key in layers:
            var = tk.BooleanVar(value=self.params.get(key, True))
            self._layer_vars[key] = var
            cb = ttk.Checkbutton(tog_frame, text=label, variable=var,
                                 command=lambda k=key, v=var: self._on_toggle(k, v))
            cb.pack(anchor="w", pady=1)

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Image overlay ────────────────────────────────────────────────────
        img_frame = ttk.Frame(root)
        img_frame.pack(fill="x", **pad)
        ttk.Label(img_frame, text="Image Overlay", font=("Courier", 10, "bold")).pack(anchor="w")

        self._img_label = tk.Label(img_frame, text="No image loaded",
                                   bg=BG, fg="#888888", font=("Courier", 8))
        self._img_label.pack(anchor="w", pady=(2, 4))

        btn_row = ttk.Frame(img_frame)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Load Image …",
                   command=self._on_load_image).pack(side="left")
        ttk.Button(btn_row, text="Clear",
                   command=self._on_clear_image).pack(side="left", padx=(6, 0))

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Audio device selector ─────────────────────────────────────────────
        dev_frame = ttk.Frame(root)
        dev_frame.pack(fill="x", **pad)
        ttk.Label(dev_frame, text="Audio Input", font=("Courier", 10, "bold")).grid(
            row=0, column=0, sticky="w")

        self._device_var = tk.StringVar(value="Default")
        self._dev_combo  = ttk.Combobox(dev_frame, textvariable=self._device_var,
                                        state="readonly", width=20)
        self._dev_combo.grid(row=1, column=0, pady=(4, 0), sticky="ew")
        self._dev_combo.bind("<<ComboboxSelected>>", self._on_device_change)
        # Devices are populated by the main thread via set_devices()

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=10, pady=6)

        # ── Quit button ───────────────────────────────────────────────────────
        ttk.Button(root, text="Quit", command=self._on_close).pack(**pad, pady=(0, 12))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _add_slider(self, parent, label: str, key: str,
                    lo: float, hi: float, init: float, row: int):
        BG = "#1a1a2e"
        FG = "#e0e0e0"

        tk.Label(parent, text=label, bg=BG, fg=FG,
                 font=("Courier", 9)).grid(row=row, column=0, sticky="w", pady=2)

        val_var = tk.DoubleVar(value=init)
        val_lbl = tk.Label(parent, textvariable=val_var, bg=BG, fg="#e94560",
                           font=("Courier", 9), width=4)
        val_lbl.grid(row=row, column=2, padx=(6, 0))

        def on_slide(v, k=key, vv=val_var):
            fv = round(float(v), 2)
            self.params[k] = fv
            vv.set(fv)

        sl = ttk.Scale(parent, from_=lo, to=hi, orient="horizontal",
                       variable=val_var, command=on_slide, length=180)
        sl.set(init)
        sl.grid(row=row, column=1, padx=(10, 0))

    def _on_palette_change(self, _event=None):
        self.params["palette"] = self._palette_var.get()

    def _on_toggle(self, key: str, var: tk.BooleanVar):
        self.params[key] = var.get()

    def _on_load_image(self):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All files", "*.*")]
        )
        if path:
            self._img_label.config(text=path.split("/")[-1])
            self.events.put({"type": EVT_LOAD_IMAGE, "path": path})

    def _on_clear_image(self):
        self._img_label.config(text="No image loaded")
        self.events.put({"type": EVT_CLEAR_IMAGE})

    def _on_device_change(self, _event=None):
        selection = self._device_var.get()
        # Parse "index: name" format
        try:
            idx = int(selection.split(":")[0])
        except (ValueError, IndexError):
            idx = None
        self.events.put({"type": "set_device", "index": idx})

    def set_devices(self, devices: list[tuple[int, str]]):
        """Called from main thread to populate the audio device dropdown."""
        if self._root is None:
            return
        values = ["Default"] + [f"{i}: {name}" for i, name in devices]
        def _update():
            self._dev_combo["values"] = values
        self._root.after(0, _update)
