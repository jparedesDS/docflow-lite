"""Notificaciones toast — banners no intrusivos en la esquina superior derecha.

Sin dependencias externas (siempre funcionan dentro de la app). Si está
instalado `winotify`, además lanza una notificación nativa de Windows
(best-effort, para cuando la ventana no tiene el foco).
"""

import logging

import customtkinter as ctk

from gui import theme

logger = logging.getLogger(__name__)

_KIND_COLOR = {
    "info": theme.ACCENT, "success": theme.GREEN,
    "warn": theme.AMBER, "error": theme.RED,
}


class NotificationManager:
    """Gestiona toasts apilados sobre una ventana (master)."""

    def __init__(self, master, width: int = 330, max_visible: int = 4):
        self.master = master
        self.width = width
        self.max_visible = max_visible
        self._active: list[ctk.CTkFrame] = []

    # ── API ──────────────────────────────────────────────────────────────────

    def notify(self, title: str, message: str = "", kind: str = "info",
               duration_ms: int = 6500, native: bool = True) -> None:
        if native:
            self._native(title, message)
        try:
            self._toast(title, message, kind, duration_ms)
        except Exception as exc:  # noqa: BLE001 — nunca debe romper la app
            logger.debug("toast falló: %s", exc)

    # ── Toast in-app ───────────────────────────────────────────────────────────

    def _toast(self, title, message, kind, duration_ms) -> None:
        color = _KIND_COLOR.get(kind, theme.ACCENT)
        card = ctk.CTkFrame(self.master, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)

        bar = ctk.CTkFrame(card, fg_color=color, width=4, corner_radius=2)
        bar.pack(side="left", fill="y", padx=(3, 0), pady=3)

        body = ctk.CTkFrame(card, fg_color="transparent", width=self.width - 28)
        body.pack(side="left", fill="both", expand=True, padx=theme.SPACE_3, pady=theme.SPACE_2)
        body.pack_propagate(False)

        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=title, font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MAIN,
                     anchor="w", justify="left", wraplength=self.width - 70).pack(
            side="left", fill="x", expand=True)
        ctk.CTkButton(top, text="✕", width=18, height=18, corner_radius=4,
                      fg_color="transparent", hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_MUTED, font=theme.font(10),
                      command=lambda: self._dismiss(card)).pack(side="right")
        if message:
            ctk.CTkLabel(body, text=message, font=theme.FONT_TINY, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=self.width - 40).pack(
                anchor="w", pady=(2, 0))

        # altura según contenido
        body.update_idletasks()
        h = max(48, body.winfo_reqheight() + 6)
        card.configure(width=self.width, height=h)
        card.pack_propagate(False)

        self._active.append(card)
        # recorta si hay demasiados
        while len(self._active) > self.max_visible:
            self._dismiss(self._active[0])
        self._reposition()
        self.master.after(duration_ms, lambda: self._dismiss(card))

    def _dismiss(self, card) -> None:
        if card in self._active:
            self._active.remove(card)
        try:
            if card.winfo_exists():
                card.place_forget()
                card.destroy()
        except Exception:
            pass
        self._reposition()

    def _reposition(self) -> None:
        y = 16
        for card in list(self._active):
            if not card.winfo_exists():
                continue
            try:
                card.place(relx=1.0, x=-18, y=y, anchor="ne")
                card.lift()
                card.update_idletasks()
                y += card.winfo_height() + 8
            except Exception:
                pass

    # ── Nativo (best-effort) ──────────────────────────────────────────────────

    def _native(self, title, message) -> None:
        try:
            from winotify import Notification
            Notification(app_id="DocFlow Lite", title=title,
                         msg=message or "").show()
        except Exception:
            pass  # winotify no instalado → solo toast in-app
