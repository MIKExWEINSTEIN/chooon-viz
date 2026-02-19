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
from tkinter import ttk, filedialog
from typing import Optional

from visuals import PALETTE_NAMES, SYMMETRY_MODES


# ── events emitted into the queue ─────────────────────────────────────────────
EVT_LOAD_IMAGE      = "load_image"
EVT_CLEAR_IMAGE     = "clear_image"
EVT_REBUILD_OVERLAY = "rebuild_overlay"   # re-apply symmetry + outline
EVT_QUIT            = "quit"


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
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="ControlPanel")

    def start(self):
        self._thread.start()

    def stop(self):
        if self._root:
            try:
                self._root.quit()
            except Exception:
                pass

    # ── internals ─────────────────────────────────────────────────────────────

    def _run(self):
        self._root = tk.Tk()
        self._root.title("chooon-viz controls")
        self._root.resizable(False, False)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#1a1a2e")

        # Make the window scrollable for smaller screens
        canvas     = tk.Canvas(self._root, bg="#1a1a2e", highlightthickness=0,
                                width=310, height=680)
        scrollbar  = ttk.Scrollbar(self._root, orient="vertical",
                                    command=canvas.yview)
        self._frame = tk.Frame(canvas, bg="#1a1a2e")

        self._frame.bind("<Configure>",
                         lambda e: canvas.configure(
                             scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=self._frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left",   fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mouse-wheel scrolling
        canvas.bind_all("<MouseWheel>",
                         lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        canvas.bind_all("<Button-4>",
                         lambda e: canvas.yview_scroll(-1, "units"))
        canvas.bind_all("<Button-5>",
                         lambda e: canvas.yview_scroll(1, "units"))

        self._build_ui(self._frame)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _on_close(self):
        self.events.put({"type": EVT_QUIT})
        self._root.destroy()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, root):
        BG  = "#1a1a2e"
        FG  = "#e0e0e0"
        ACC = "#16213e"
        HL  = "#0f3460"
        SL  = "#e94560"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale",
                         background=BG, troughcolor=ACC,
                         sliderlength=18, sliderrelief="flat")
        style.configure("TLabel",      background=BG, foreground=FG)
        style.configure("TFrame",      background=BG)
        style.configure("TButton",
                         background=HL, foreground=FG,
                         relief="flat", padding=4)
        style.map("TButton",      background=[("active", SL)])
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TCombobox",
                         fieldbackground=ACC, background=ACC,
                         foreground=FG, selectbackground=HL)
        style.configure("TSeparator", background="#2a2a4a")

        pad = dict(padx=10, pady=4)

        # ── Title ────────────────────────────────────────────────────────────
        tk.Label(root, text="chooon-viz", font=("Courier", 16, "bold"),
                 bg=BG, fg=SL).pack(**pad, pady=(12, 0))

        self._sep(root)

        # ── Animation sliders ─────────────────────────────────────────────────
        self._section(root, "Animation")
        sf = ttk.Frame(root)
        sf.pack(fill="x", **pad)
        self._add_slider(sf, "Speed",     "speed",     0.1, 4.0,
                          self.params.get("speed",     1.0), row=0)
        self._add_slider(sf, "Intensity", "intensity", 0.0, 3.0,
                          self.params.get("intensity", 1.0), row=1)

        self._sep(root)

        # ── Colour palette ───────────────────────────────────────────────────
        self._section(root, "Color Palette")
        pf = ttk.Frame(root)
        pf.pack(fill="x", **pad)
        self._palette_var = tk.StringVar(
            value=self.params.get("palette", PALETTE_NAMES[0]))
        combo = ttk.Combobox(pf, textvariable=self._palette_var,
                             values=PALETTE_NAMES, state="readonly", width=16)
        combo.pack(anchor="w")
        combo.bind("<<ComboboxSelected>>", self._on_palette_change)

        self._sep(root)

        # ── Layer toggles ────────────────────────────────────────────────────
        self._section(root, "Layers")
        lf = ttk.Frame(root)
        lf.pack(fill="x", **pad)
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
            ttk.Checkbutton(lf, text=label, variable=var,
                            command=lambda k=key, v=var: self._on_toggle(k, v)
                            ).pack(anchor="w", pady=1)

        self._sep(root)

        # ── Image overlay ─────────────────────────────────────────────────────
        self._section(root, "Image Overlay")
        imgf = ttk.Frame(root)
        imgf.pack(fill="x", **pad)

        self._img_label = tk.Label(imgf, text="No image loaded",
                                   bg=BG, fg="#888888",
                                   font=("Courier", 8), wraplength=260,
                                   justify="left")
        self._img_label.pack(anchor="w", pady=(2, 4))

        # Supported formats note
        tk.Label(imgf,
                 text="Accepts: PNG · JPG · GIF · BMP · WEBP · TIFF · any PIL-supported format\n"
                      "Any resolution — automatically scaled & processed.",
                 bg=BG, fg="#666699", font=("Courier", 7),
                 justify="left", wraplength=270).pack(anchor="w", pady=(0, 4))

        btn_row = ttk.Frame(imgf)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Load Image …",
                   command=self._on_load_image).pack(side="left")
        ttk.Button(btn_row, text="Clear",
                   command=self._on_clear_image).pack(side="left", padx=(6, 0))

        self._sep(root)

        # ── Image transforms ──────────────────────────────────────────────────
        self._section(root, "Image Transforms")
        xf = ttk.Frame(root)
        xf.pack(fill="x", **pad)

        # ·· Symmetry mode ····················································
        tk.Label(xf, text="Symmetry", bg=BG, fg=FG,
                 font=("Courier", 9)).grid(row=0, column=0, sticky="w", pady=2)
        self._sym_var = tk.StringVar(
            value=self.params.get("symmetry_mode", "None"))
        sym_combo = ttk.Combobox(xf, textvariable=self._sym_var,
                                  values=SYMMETRY_MODES, state="readonly",
                                  width=16)
        sym_combo.grid(row=0, column=1, padx=(8, 0), sticky="w")
        sym_combo.bind("<<ComboboxSelected>>", self._on_symmetry_change)

        # Mode descriptions
        self._sym_desc = tk.Label(xf, text=self._sym_description("None"),
                                   bg=BG, fg="#8899bb",
                                   font=("Courier", 7), wraplength=260,
                                   justify="left")
        self._sym_desc.grid(row=1, column=0, columnspan=2,
                              sticky="w", pady=(0, 6))

        # ·· Outline ··························································
        tk.Label(xf, text="Outline", bg=BG, fg=FG,
                 font=("Courier", 9, "bold")).grid(row=2, column=0,
                                                    columnspan=2, sticky="w",
                                                    pady=(4, 0))

        out_row = ttk.Frame(xf)
        out_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)

        self._outline_var = tk.BooleanVar(
            value=self.params.get("outline_enabled", False))
        ttk.Checkbutton(out_row, text="Enable outline",
                        variable=self._outline_var,
                        command=self._on_outline_toggle).pack(side="left")

        self._glow_var = tk.BooleanVar(
            value=self.params.get("outline_glow", True))
        ttk.Checkbutton(out_row, text="Glow",
                        variable=self._glow_var,
                        command=self._on_glow_toggle).pack(side="left",
                                                           padx=(10, 0))

        # Outline strength slider
        of = ttk.Frame(xf)
        of.grid(row=4, column=0, columnspan=2, sticky="ew")
        self._add_slider(of, "Strength", "outline_strength", 0.0, 3.0,
                          self.params.get("outline_strength", 1.0), row=0)

        tk.Label(xf,
                 text="Outline colour follows the active palette and pulses\n"
                      "brighter on every detected beat.",
                 bg=BG, fg="#666699", font=("Courier", 7),
                 justify="left", wraplength=270).grid(
                     row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        self._sep(root)

        # ── Audio device ──────────────────────────────────────────────────────
        self._section(root, "Audio Input")
        df = ttk.Frame(root)
        df.pack(fill="x", **pad)
        self._device_var = tk.StringVar(value="Default")
        self._dev_combo  = ttk.Combobox(df, textvariable=self._device_var,
                                         state="readonly", width=24)
        self._dev_combo.pack(anchor="w")
        self._dev_combo.bind("<<ComboboxSelected>>", self._on_device_change)

        self._sep(root)

        # ── Quit ──────────────────────────────────────────────────────────────
        ttk.Button(root, text="Quit", command=self._on_close).pack(
            **pad, pady=(0, 14))

    # ── layout helpers ────────────────────────────────────────────────────────

    def _sep(self, parent):
        ttk.Separator(parent, orient="horizontal").pack(
            fill="x", padx=10, pady=6)

    def _section(self, parent, title: str):
        BG = "#1a1a2e"
        SL = "#e94560"
        tk.Label(parent, text=title, font=("Courier", 10, "bold"),
                 bg=BG, fg=SL).pack(padx=10, anchor="w", pady=(2, 0))

    def _add_slider(self, parent, label: str, key: str,
                    lo: float, hi: float, init: float, row: int):
        BG = "#1a1a2e"
        FG = "#e0e0e0"
        SL = "#e94560"

        tk.Label(parent, text=label, bg=BG, fg=FG,
                 font=("Courier", 9)).grid(row=row, column=0,
                                           sticky="w", pady=2)
        val_var = tk.DoubleVar(value=init)
        tk.Label(parent, textvariable=val_var, bg=BG, fg=SL,
                 font=("Courier", 9), width=4).grid(row=row, column=2,
                                                     padx=(6, 0))

        def on_slide(v, k=key, vv=val_var):
            fv = round(float(v), 2)
            self.params[k] = fv
            vv.set(fv)

        sl = ttk.Scale(parent, from_=lo, to=hi, orient="horizontal",
                       variable=val_var, command=on_slide, length=175)
        sl.set(init)
        sl.grid(row=row, column=1, padx=(10, 0))

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_palette_change(self, _=None):
        self.params["palette"] = self._palette_var.get()

    def _on_toggle(self, key: str, var: tk.BooleanVar):
        self.params[key] = var.get()

    def _on_load_image(self):
        path = filedialog.askopenfilename(
            title="Select image",
            filetypes=[
                ("Image files",
                 "*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tiff *.tif "
                 "*.ico *.ppm *.pgm *.pbm *.pnm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            name = path.split("/")[-1]
            self._img_label.config(text=name)
            self.events.put({"type": EVT_LOAD_IMAGE, "path": path})

    def _on_clear_image(self):
        self._img_label.config(text="No image loaded")
        self.events.put({"type": EVT_CLEAR_IMAGE})

    def _on_symmetry_change(self, _=None):
        mode = self._sym_var.get()
        self.params["symmetry_mode"] = mode
        self._sym_desc.config(text=self._sym_description(mode))
        # Rebuild only if an image is already loaded
        self.events.put({"type": EVT_REBUILD_OVERLAY})

    def _on_outline_toggle(self):
        self.params["outline_enabled"] = self._outline_var.get()

    def _on_glow_toggle(self):
        self.params["outline_glow"] = self._glow_var.get()

    def _on_device_change(self, _=None):
        sel = self._device_var.get()
        try:
            idx = int(sel.split(":")[0])
        except (ValueError, IndexError):
            idx = None
        self.events.put({"type": "set_device", "index": idx})

    @staticmethod
    def _sym_description(mode: str) -> str:
        descs = {
            "None":           "Original image, no transformation.",
            "Mirror H":       "Left half mirrored onto the right — symmetric about the vertical centre line.",
            "Mirror V":       "Top half mirrored downward — symmetric about the horizontal centre line.",
            "4-Way":          "Top-left quadrant reflected into all four quadrants. Creates a mandala / rorschach pattern.",
            "Kaleidoscope 4": "4-segment polar kaleidoscope. Centre-crops to square then folds into 4 wedge reflections.",
            "Kaleidoscope 8": "Classic 8-segment stained-glass kaleidoscope using polar coordinate folding.",
        }
        return descs.get(mode, "")

    def set_devices(self, devices: list[tuple[int, str]]):
        """Called from main thread to populate the audio device dropdown."""
        if self._root is None:
            return
        values = ["Default"] + [f"{i}: {name}" for i, name in devices]
        self._root.after(0, lambda: self._dev_combo.configure(values=values))
