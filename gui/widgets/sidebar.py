"""Sidebar de navegación premium — indicador vertical de item activo + hover sutil."""

import webbrowser

import customtkinter as ctk

from gui import theme

PORTFOLIO_URL = "https://jparedesds.github.io/"


class Sidebar(ctk.CTkFrame):
    """Sidebar con header, lista de items (barra activa lateral), toggle tema y footer.

    Cada item es un dict con: key, label, icon (opcional).
    `on_select(key)` se invoca al hacer click.
    `on_toggle_theme()` (opcional) se invoca al pulsar el toggle de tema.
    """

    WIDTH = 232

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
        self._items: dict[str, dict] = {}
        self._active_key: str | None = None

        # ── Brand header ──────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_2))

        ctk.CTkLabel(
            header,
            text="◆  DocFlow",
            font=(theme.FONT_FAMILY, 17, "bold"),
            text_color=theme.TEXT_MAIN,
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Lite",
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.ACCENT,
            anchor="w",
        ).pack(anchor="w")

        # Separador sutil
        sep = ctk.CTkFrame(self, fg_color=theme.BORDER, height=1)
        sep.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_3))

        # ── Items con barra de activo ─────────────────────────────────────
        for item in items:
            self._build_nav_item(item)

        # ── Footer (anclado abajo) ────────────────────────────────────────
        footer_box = ctk.CTkFrame(self, fg_color="transparent")
        footer_box.pack(side="bottom", fill="x", padx=theme.SPACE_3, pady=theme.SPACE_4)

        # Toggle de tema
        if on_toggle_theme is not None:
            is_dark = theme.current_mode() == "dark"
            toggle_text = "☀  Modo claro" if is_dark else "🌙  Modo oscuro"
            ctk.CTkButton(
                footer_box, text=toggle_text, anchor="w",
                font=(theme.FONT_FAMILY, 11),
                height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_MD,
                fg_color="transparent", hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB,
                border_width=1, border_color=theme.BORDER,
                command=on_toggle_theme,
            ).pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_2))

        # Footer text con link al portfolio
        if footer:
            credit_row = ctk.CTkFrame(footer_box, fg_color="transparent")
            credit_row.pack(anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_1, 0))

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

    # ── Construcción de cada item ─────────────────────────────────────────

    def _build_nav_item(self, item: dict) -> None:
        """Cada item es un frame con: barra activa (3px) + botón.

        La barra se hace visible cuando el item está activo.
        """
        key = item["key"]

        # Container con la barra lateral + botón
        row = ctk.CTkFrame(self, fg_color="transparent", height=theme.HEIGHT_BUTTON + 4)
        row.pack(fill="x", padx=(0, theme.SPACE_2), pady=1)
        row.pack_propagate(False)

        # Barra vertical de indicador activo (3px ancho)
        bar = ctk.CTkFrame(row, width=3, fg_color="transparent", corner_radius=0)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        # Botón principal
        btn = ctk.CTkButton(
            row,
            text=f"  {item.get('icon', '')}   {item['label']}",
            anchor="w",
            font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON,
            corner_radius=theme.RADIUS_MD,
            fg_color="transparent",
            hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB,
            command=lambda k=key: self._handle_click(k),
        )
        btn.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_1, 0))

        self._items[key] = {"row": row, "bar": bar, "btn": btn}

    def _handle_click(self, key: str) -> None:
        self.set_active(key)
        self._on_select(key)

    def set_active(self, key: str) -> None:
        if self._active_key == key:
            return
        self._active_key = key
        for k, item in self._items.items():
            if k == key:
                item["bar"].configure(fg_color=theme.ACCENT)
                item["btn"].configure(
                    fg_color=theme.ACCENT_SOFT,
                    text_color=theme.TEXT_MAIN,
                    hover_color=theme.ACCENT_SOFT,
                )
            else:
                item["bar"].configure(fg_color="transparent")
                item["btn"].configure(
                    fg_color="transparent",
                    text_color=theme.TEXT_SUB,
                    hover_color=theme.BG_INPUT,
                )
