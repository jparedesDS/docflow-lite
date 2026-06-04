"""LoginWindow — pantalla de autenticación previa a la app principal.

Flujo:
1. Usuario introduce iniciales + password.
2. Si OK y `must_change_password=True` → diálogo de cambio obligatorio.
3. Si OK normal → cierra esta ventana y arranca DocFlowLiteApp.
4. Si cierra sin autenticar → la app no arranca (sys.exit).
"""

from __future__ import annotations

import webbrowser
from typing import Optional

import customtkinter as ctk

from core import auth
from gui import theme

PORTFOLIO_URL = "https://jparedesds.github.io/"


class LoginWindow(ctk.CTk):
    """Ventana raíz de login. Es CTk (no CTkToplevel) porque corre antes de la app."""

    WIDTH = 460
    HEIGHT = 560

    def __init__(self):
        # Aplicar modo desde preferencias antes de crear widgets
        from core.preferences import get_theme
        mode = get_theme()
        ctk.set_appearance_mode(mode)
        ctk.set_default_color_theme("dark-blue" if mode == "dark" else "blue")

        super().__init__(fg_color=theme.BG_PAGE)
        self.title("DocFlow Lite — Iniciar sesión")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.resizable(False, False)
        self._center_on_screen()

        self.user: Optional[dict] = None  # se setea al autenticar
        self._build_layout()

        # Enter para enviar
        self.bind("<Return>", lambda _e: self._submit())
        self.bind("<KP_Enter>", lambda _e: self._submit())

    def _center_on_screen(self) -> None:
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - self.WIDTH) // 2
        y = (sh - self.HEIGHT) // 2
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    # ── Layout ───────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.pack(fill="both", expand=True, padx=theme.SPACE_8, pady=theme.SPACE_8)

        # Brand
        ctk.CTkLabel(
            wrapper, text="◆  DocFlow",
            font=theme.font(26, "bold"),
            text_color=theme.TEXT_MAIN,
        ).pack(anchor="center", pady=(theme.SPACE_4, 0))

        ctk.CTkLabel(
            wrapper, text="Lite",
            font=theme.font(13, "bold"),
            text_color=theme.ACCENT,
        ).pack(anchor="center", pady=(0, theme.SPACE_6))

        # Card de login
        card = ctk.CTkFrame(
            wrapper, fg_color=theme.BG_CARD,
            corner_radius=theme.RADIUS_LG,
            border_width=1, border_color=theme.BORDER,
        )
        card.pack(fill="x", pady=(0, theme.SPACE_4))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=theme.SPACE_5, pady=theme.SPACE_5)

        ctk.CTkLabel(
            inner, text="Iniciar sesión",
            font=theme.FONT_HEADING, text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")

        ctk.CTkLabel(
            inner, text="Acceso restringido a Document Controllers",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, theme.SPACE_4))

        # Iniciales
        ctk.CTkLabel(
            inner, text="INICIALES", font=theme.FONT_LABEL,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, theme.SPACE_1))
        self.ent_initials = ctk.CTkEntry(
            inner, placeholder_text="JP",
            height=theme.HEIGHT_INPUT + 4, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_initials.pack(fill="x", pady=(0, theme.SPACE_3))

        # Password
        ctk.CTkLabel(
            inner, text="CONTRASEÑA", font=theme.FONT_LABEL,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", pady=(0, theme.SPACE_1))
        self.ent_password = ctk.CTkEntry(
            inner, placeholder_text="••••••••", show="•",
            height=theme.HEIGHT_INPUT + 4, corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_password.pack(fill="x", pady=(0, theme.SPACE_4))

        # Error label (oculto inicialmente)
        self.lbl_error = ctk.CTkLabel(
            inner, text="", font=theme.FONT_SMALL,
            text_color=theme.RED, anchor="w", justify="left", wraplength=380,
        )
        self.lbl_error.pack(anchor="w", pady=(0, theme.SPACE_2))

        # Botón submit
        self.btn_submit = ctk.CTkButton(
            inner, text="Iniciar sesión", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON + 4, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._submit,
        )
        self.btn_submit.pack(fill="x")

        # Hint contraseña por defecto
        ctk.CTkLabel(
            inner, text="Contraseña por defecto: Aa123456 (se forzará cambio al primer acceso)",
            font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
            anchor="w", justify="left", wraplength=380,
        ).pack(anchor="w", pady=(theme.SPACE_3, 0))

        # Footer con credit + link
        footer = ctk.CTkFrame(wrapper, fg_color="transparent")
        footer.pack(side="bottom", fill="x")
        credit = ctk.CTkFrame(footer, fg_color="transparent")
        credit.pack(anchor="center")
        ctk.CTkLabel(
            credit, text="DocFlow Lite v0.1  ·  © 2026  ",
            font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
        ).pack(side="left")
        link = ctk.CTkLabel(
            credit, text="jparedesDS",
            font=theme.FONT_TINY_BOLD, text_color=theme.ACCENT, cursor="hand2",
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: webbrowser.open(PORTFOLIO_URL))

        # Focus inicial
        self.ent_initials.focus_set()

    # ── Acciones ─────────────────────────────────────────────────────────────

    def _submit(self) -> None:
        initials = self.ent_initials.get().strip().upper()
        password = self.ent_password.get()

        if not initials or not password:
            self._show_error("Introduce iniciales y contraseña.")
            return

        self.btn_submit.configure(state="disabled", text="Verificando…")
        self.update_idletasks()

        user, err = auth.login(initials, password)

        if user is None:
            self._show_error(err or "Error de autenticación.")
            self.btn_submit.configure(state="normal", text="Iniciar sesión")
            self.ent_password.delete(0, "end")
            self.ent_password.focus_set()
            return

        # Si debe cambiar contraseña → diálogo modal de cambio
        if user.get("must_change_password"):
            ok = ChangePasswordDialog(self, user, initial_change=True).result_ok
            if not ok:
                self._show_error("Debes cambiar la contraseña para entrar.")
                self.btn_submit.configure(state="normal", text="Iniciar sesión")
                return

        # Login OK
        self.user = user
        self.destroy()

    def _show_error(self, msg: str) -> None:
        self.lbl_error.configure(text=msg)


# ════════════════════════════════════════════════════════════════════════════
#  Cambio de contraseña obligatorio
# ════════════════════════════════════════════════════════════════════════════

class ChangePasswordDialog(ctk.CTkToplevel):
    """Modal que fuerza al usuario a cambiar la contraseña por defecto."""

    def __init__(self, master, user: dict, initial_change: bool = False):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title("Cambiar contraseña")
        self.geometry("440x420")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._user = user
        self.result_ok = False

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=theme.SPACE_5)

        ctk.CTkLabel(
            inner, text="Cambiar contraseña",
            font=theme.FONT_HEADING, text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")

        intro = (
            "Es tu primer acceso. Debes cambiar la contraseña por defecto."
            if initial_change
            else f"Usuario: {user.get('nombre')} ({user.get('initials')})"
        )
        ctk.CTkLabel(
            inner, text=intro, font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="w", justify="left", wraplength=380,
        ).pack(anchor="w", pady=(theme.SPACE_1, theme.SPACE_3))

        ctk.CTkLabel(inner, text="NUEVA CONTRASEÑA", font=theme.FONT_LABEL,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_new = ctk.CTkEntry(
            inner, show="•", height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_new.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_2))

        ctk.CTkLabel(inner, text="CONFIRMAR CONTRASEÑA", font=theme.FONT_LABEL,
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.ent_confirm = ctk.CTkEntry(
            inner, show="•", height=theme.HEIGHT_INPUT,
            corner_radius=theme.RADIUS_MD,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        self.ent_confirm.pack(fill="x", pady=(theme.SPACE_1, theme.SPACE_3))

        ctk.CTkLabel(
            inner, text="Mínimo 6 caracteres.",
            font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w")

        self.lbl_error = ctk.CTkLabel(
            inner, text="", font=theme.FONT_SMALL,
            text_color=theme.RED, anchor="w", justify="left", wraplength=380,
        )
        self.lbl_error.pack(anchor="w", pady=(theme.SPACE_2, theme.SPACE_2))

        footer = ctk.CTkFrame(inner, fg_color="transparent")
        footer.pack(fill="x", side="bottom")
        ctk.CTkButton(
            footer, text="Cancelar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(theme.SPACE_2, 0))
        ctk.CTkButton(
            footer, text="Cambiar y entrar", font=theme.FONT_BUTTON,
            height=theme.HEIGHT_BUTTON, corner_radius=theme.RADIUS_MD,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#FFFFFF",
            command=self._submit,
        ).pack(side="right")

        self.ent_new.focus_set()
        self.bind("<Return>", lambda _e: self._submit())

        # Bloquear hasta que se cierre
        self.wait_window()

    def _submit(self) -> None:
        new = self.ent_new.get()
        conf = self.ent_confirm.get()
        if new != conf:
            self.lbl_error.configure(text="Las contraseñas no coinciden.")
            return
        ok, err = auth.change_password(self._user["initials"], new)
        if not ok:
            self.lbl_error.configure(text=err or "No se pudo cambiar la contraseña.")
            return
        self.result_ok = True
        self.destroy()
