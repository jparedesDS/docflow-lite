"""Sidebar de navegación — frame fijo a la izquierda con botones de sección."""

import webbrowser

import customtkinter as ctk

from gui import theme

PORTFOLIO_URL = "https://jparedesds.github.io/"


class Sidebar(ctk.CTkFrame):
    """Sidebar con header, lista de botones, toggle de tema y footer.

    Cada item es un dict con: key, label, icon (opcional).
    `on_select(key)` se invoca al hacer click.
    `on_toggle_theme()` (opcional) se invoca al pulsar el toggle de tema.
    """

    WIDTH = 220

    def __init__(
        self, master, items: list[dict], on_select,
        on_toggle_theme=None, footer: str = "", **kwargs,
    ):
        super().__init__(
            master,
            width=self.WIDTH,
            corner_radius=0,
            fg_color=theme.BG_SIDEBAR,
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._on_select = on_select
        self._on_toggle_theme = on_toggle_theme
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._active_key: str | None = None

        # ── Brand header ────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent", height=64)
        header.pack(fill="x", padx=18, pady=(18, 8))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="◆  DocFlow",
            font=(theme.FONT_FAMILY, 18, "bold"),
            text_color=theme.TEXT_MAIN,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Lite",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.ACCENT,
            anchor="w",
        ).pack(anchor="w")

        # Separador
        sep = ctk.CTkFrame(self, fg_color=theme.BORDER, height=1)
        sep.pack(fill="x", padx=14, pady=(4, 14))

        # ── Botones ─────────────────────────────────────────────────────────
        for item in items:
            btn = ctk.CTkButton(
                self,
                text=f"  {item.get('icon', '')}   {item['label']}",
                anchor="w",
                font=theme.FONT_BUTTON,
                height=42,
                corner_radius=10,
                fg_color="transparent",
                hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB,
                command=lambda k=item["key"]: self._handle_click(k),
            )
            btn.pack(fill="x", padx=12, pady=2)
            self._buttons[item["key"]] = btn

        # ── Footer (anclado abajo) ──────────────────────────────────────────
        footer_box = ctk.CTkFrame(self, fg_color="transparent")
        footer_box.pack(side="bottom", fill="x", padx=12, pady=14)

        # Toggle de tema
        if on_toggle_theme is not None:
            is_dark = theme.current_mode() == "dark"
            toggle_text = "☀  Modo claro" if is_dark else "🌙  Modo oscuro"
            ctk.CTkButton(
                footer_box, text=toggle_text, anchor="w",
                font=(theme.FONT_FAMILY, 11),
                height=32, corner_radius=8,
                fg_color="transparent", hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                command=on_toggle_theme,
            ).pack(fill="x", pady=(0, 8))

        # Footer text con link al portfolio (jparedesDS clicable)
        if footer:
            credit_row = ctk.CTkFrame(footer_box, fg_color="transparent")
            credit_row.pack(anchor="w", padx=6)

            ctk.CTkLabel(
                credit_row, text="© 2026  ",
                font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
            ).pack(side="left")

            link = ctk.CTkLabel(
                credit_row, text="jparedesDS",
                font=(theme.FONT_FAMILY, 10, "bold"),
                text_color=theme.ACCENT, cursor="hand2",
            )
            link.pack(side="left")
            link.bind("<Button-1>", lambda _e: webbrowser.open(PORTFOLIO_URL))
            link.bind("<Enter>", lambda _e: link.configure(text_color=theme.ACCENT_HOVER))
            link.bind("<Leave>", lambda _e: link.configure(text_color=theme.ACCENT))

    def _handle_click(self, key: str) -> None:
        self.set_active(key)
        self._on_select(key)

    def set_active(self, key: str) -> None:
        if self._active_key == key:
            return
        self._active_key = key
        for k, btn in self._buttons.items():
            if k == key:
                btn.configure(fg_color=theme.ACCENT, text_color="white", hover_color=theme.ACCENT_HOVER)
            else:
                btn.configure(fg_color="transparent", text_color=theme.TEXT_SUB, hover_color=theme.BG_INPUT)
