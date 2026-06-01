"""Diálogo modal para seleccionar entre los 4 temas disponibles.

Cada opción se muestra como una card clickable con un preview de los colores
principales (BG_PAGE, ACCENT, TEXT_MAIN) y la familia tipográfica.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from core.preferences import get_theme
from gui import theme


# Catálogo visual de los 4 modos. Colores HARDCODEADOS aquí para que cada card
# muestre la apariencia REAL del tema (no la del tema actualmente activo).
THEMES: list[dict] = [
    {
        "key":   "light",
        "label": "Claro",
        "subtitle": "Linear / Vercel · indigo",
        "icon":  "☀",
        "bg":    "#F7F8FA", "card": "#FFFFFF", "accent": "#4F46E5",
        "text":  "#0F172A", "sub":  "#475569", "border": "#E5E7EB",
        "font":  "Segoe UI",
    },
    {
        "key":   "dark",
        "label": "Oscuro",
        "subtitle": "Linear / Vercel · indigo",
        "icon":  "☾",
        "bg":    "#0F1117", "card": "#1A1D27", "accent": "#4F46E5",
        "text":  "#F1F5F9", "sub":  "#B4BCD0", "border": "#2E3244",
        "font":  "Segoe UI",
    },
    {
        "key":   "light-coral",
        "label": "Claro · Coral",
        "subtitle": "Cream + coral · estilo terminal",
        "icon":  "✦",
        "bg":    "#FAF9F5", "card": "#FFFFFF", "accent": "#D97757",
        "text":  "#1F1E1D", "sub":  "#6B6760", "border": "#E5E4DD",
        "font":  "Cascadia Code",
    },
    {
        "key":   "dark-coral",
        "label": "Oscuro · Coral",
        "subtitle": "Warm dark + coral · estilo terminal",
        "icon":  "✦",
        "bg":    "#1F1E1D", "card": "#262624", "accent": "#D97757",
        "text":  "#F0EEE6", "sub":  "#A8A29E", "border": "#3D3B38",
        "font":  "Cascadia Code",
    },
]


class ThemePickerDialog(ctk.CTkToplevel):
    """Modal con las 4 cards de tema. Llama a `on_apply(key)` al confirmar."""

    SELECTED_BORDER_W = 3
    DEFAULT_BORDER_W = 1

    def __init__(self, master, on_apply: Callable[[str], None]):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Aspecto")
        self.geometry("780x560")
        self.minsize(740, 520)
        self.resizable(False, False)

        self._on_apply = on_apply
        self._current = get_theme()
        self._selected = self._current
        # Por cada key guardamos: card frame, ribbon indicador, ribbon label
        self._cards: dict[str, dict] = {}

        self.transient(master)
        self.after(50, self._center_on_master)

        self._build()

        self.grab_set()
        self.focus_force()

    def _center_on_master(self) -> None:
        try:
            self.update_idletasks()
            mx = self.master.winfo_rootx()
            my = self.master.winfo_rooty()
            mw = self.master.winfo_width()
            mh = self.master.winfo_height()
            w = self.winfo_width()
            h = self.winfo_height()
            x = mx + (mw - w) // 2
            y = my + (mh - h) // 2
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _build(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_2))
        ctk.CTkLabel(
            header, text="Aspecto", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Elige un tema. DocFlow Lite se reiniciará para aplicarlo.",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Grid 2×2 de cards
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=theme.SPACE_3)
        for c in range(2):
            grid.grid_columnconfigure(c, weight=1, uniform="th")
        for r in range(2):
            grid.grid_rowconfigure(r, weight=1, uniform="th")

        for i, t in enumerate(THEMES):
            r, c = i // 2, i % 2
            self._build_card(grid, t).grid(
                row=r, column=c, sticky="nsew",
                padx=theme.SPACE_2, pady=theme.SPACE_2,
            )

        # Footer
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_2, theme.SPACE_5))

        # Hint a la izquierda
        ctk.CTkLabel(
            footer, text="Tip: doble-click sobre un tema para aplicarlo al instante",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(side="left")

        ctk.CTkButton(
            footer, text="Cancelar", command=self.destroy,
            **theme.button_kwargs("ghost"),
        ).pack(side="right", padx=(theme.SPACE_2, 0))

        self.btn_apply = ctk.CTkButton(
            footer, text="Aplicar", command=self._on_apply_click,
            **theme.button_kwargs("primary"),
        )
        self.btn_apply.pack(side="right")

        self._refresh_selection()

    def _build_card(self, parent, t: dict) -> ctk.CTkFrame:
        """Una card con preview real de los colores y fuente del tema."""
        outer = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD,
            border_color=theme.BORDER, border_width=self.DEFAULT_BORDER_W,
            corner_radius=theme.RADIUS_LG,
        )

        # ─── Ribbon superior ──────────────────────────────────────────────
        # Siempre presente al top. Invisible cuando no seleccionado
        # (color = BG_CARD para mimetizar); ACCENT cuando seleccionado.
        ribbon = ctk.CTkFrame(
            outer, fg_color=theme.BG_CARD, height=6, corner_radius=0,
        )
        ribbon.pack(fill="x", side="top")

        # ─── Preview del tema ─────────────────────────────────────────────
        preview = ctk.CTkFrame(
            outer, fg_color=t["bg"],
            corner_radius=theme.RADIUS_MD,
            border_color=t["border"], border_width=1, height=120,
        )
        preview.pack(fill="x", padx=theme.SPACE_3,
                     pady=(theme.SPACE_3, theme.SPACE_2))
        preview.pack_propagate(False)

        # Topbar simulada
        top = ctk.CTkFrame(preview, fg_color=t["card"], height=26, corner_radius=4)
        top.pack(fill="x", padx=8, pady=(8, 4))
        top.pack_propagate(False)
        ctk.CTkLabel(
            top, text="  ●  DocFlow Lite",
            font=(t["font"], 10, "bold"),
            text_color=t["text"], anchor="w",
        ).pack(side="left", padx=4)

        # Body con texto + pill accent
        body = ctk.CTkFrame(preview, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        ctk.CTkLabel(
            body, text="Apertura de pedidos",
            font=(t["font"], 11, "bold"),
            text_color=t["text"], anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            body, text="P-26-050 · SABIC · NIVEL",
            font=(t["font"], 9),
            text_color=t["sub"], anchor="w",
        ).pack(anchor="w")
        pill = ctk.CTkFrame(body, fg_color=t["accent"], corner_radius=10, height=18)
        pill.pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(
            pill, text="  Procesar  ", font=(t["font"], 9, "bold"),
            text_color="#FFFFFF",
        ).pack(padx=2)

        # ─── Header de la card ────────────────────────────────────────────
        info = ctk.CTkFrame(outer, fg_color="transparent")
        info.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_3))

        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(
            title_row, text=t["icon"], font=theme.FONT_HEADING,
            text_color=t["accent"], width=24,
        ).pack(side="left")
        ctk.CTkLabel(
            title_row, text=t["label"], font=theme.FONT_HEADING,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=(4, 0))

        # Etiqueta "actual" (a la izquierda del check de selección)
        if t["key"] == self._current:
            ctk.CTkLabel(
                title_row, text="actual",
                font=theme.FONT_TINY_BOLD,
                text_color=theme.TEXT_MUTED,
            ).pack(side="right", padx=(0, theme.SPACE_2))

        # Check de selección (visible solo cuando está marcada)
        check_lbl = ctk.CTkLabel(
            title_row, text="✓ seleccionado",
            font=theme.FONT_SMALL_BOLD,
            text_color=theme.ACCENT,
        )
        # No la packeamos aún

        ctk.CTkLabel(
            info, text=t["subtitle"], font=theme.FONT_SMALL,
            text_color=theme.TEXT_SUB, anchor="w", justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # ─── Click ────────────────────────────────────────────────────────
        def _on_click(_e=None, key=t["key"]):
            self._selected = key
            self._refresh_selection()

        def _on_double(_e=None, key=t["key"]):
            self._selected = key
            self._refresh_selection()
            # Aplica inmediatamente con doble-click
            self._on_apply_click()

        self._bind_recursive(outer, "<Button-1>", _on_click)
        self._bind_recursive(outer, "<Double-Button-1>", _on_double)

        self._cards[t["key"]] = {
            "outer": outer,
            "ribbon": ribbon,
            "check": check_lbl,
            "default_fg": theme.BG_CARD,
        }
        return outer

    def _bind_recursive(self, widget, sequence, handler) -> None:
        try:
            widget.bind(sequence, handler)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_recursive(child, sequence, handler)

    def _refresh_selection(self) -> None:
        """Aplica feedback visual MUY visible al cambio de selección.

        - Ribbon de 6px accent arriba (pack/forget)
        - Borde 3px en ACCENT_HOVER
        - Background del card a ACCENT_SOFT
        - Etiqueta '✓ seleccionado' visible en la cabecera
        """
        for key, refs in self._cards.items():
            outer = refs["outer"]
            ribbon = refs["ribbon"]
            check = refs["check"]
            if key == self._selected:
                ribbon.configure(fg_color=theme.ACCENT)
                outer.configure(
                    border_color=theme.ACCENT,
                    border_width=self.SELECTED_BORDER_W,
                    fg_color=theme.ACCENT_SOFT,
                )
                try:
                    check.pack(side="right")
                except Exception:
                    pass
            else:
                ribbon.configure(fg_color=refs["default_fg"])  # invisible
                outer.configure(
                    border_color=theme.BORDER,
                    border_width=self.DEFAULT_BORDER_W,
                    fg_color=refs["default_fg"],
                )
                try:
                    check.pack_forget()
                except Exception:
                    pass

        # Botón Aplicar deshabilitado si selección = actual
        if self._selected == self._current:
            self.btn_apply.configure(text="Aplicar  ·  ya activo", state="disabled")
        else:
            self.btn_apply.configure(text="Aplicar", state="normal")

    def _on_apply_click(self) -> None:
        if not self._selected or self._selected == self._current:
            self.destroy()
            return
        # Capturar referencias ANTES de destruir el toplevel
        chosen = self._selected
        callback = self._on_apply
        master = self.master

        self.destroy()
        # Diferir la aplicación al siguiente tick del event loop para que el
        # destroy se procese antes de que el callback pueda os._exit el proceso
        try:
            master.after_idle(lambda: callback(chosen))
        except Exception:
            # Si el master ya no responde, llamamos directo
            callback(chosen)
