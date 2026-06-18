"""Vista Ajustes (solo admin) — configuración y credenciales seguras + usuarios.

Pestañas: General · Fuentes de datos · Correo · Ofertas · DocuSign · IA · Usuarios.
Secretos → core.credentials (keyring/cifrado). Ajustes no secretos → preferences.
Los cambios de conexión se aplican al reiniciar (botón en la cabecera).
"""

import logging
import threading

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core import auth, credentials, preferences as pref
from core import data_source
from core.config import OFERTAS_ACCOUNTS, SECRET_ENV_MAP
from core.services import docusign as ds
from gui import theme
from gui.widgets import ui

logger = logging.getLogger(__name__)


def _entry(parent, value="", placeholder="", width=None, show=None):
    kw = dict(placeholder_text=placeholder, height=theme.HEIGHT_INPUT,
              corner_radius=theme.RADIUS_MD, fg_color=theme.BG_INPUT,
              border_color=theme.BORDER, text_color=theme.TEXT_MAIN, font=theme.FONT_SMALL)
    if width:
        kw["width"] = width
    if show:
        kw["show"] = show
    e = ctk.CTkEntry(parent, **kw)
    if value:
        e.insert(0, value)
    return e


class AjustesView(ctk.CTkFrame):
    def __init__(self, master, on_restart=None, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._on_restart = on_restart
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(header, text="Ajustes", font=theme.FONT_TITLE,
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left")
        ctk.CTkButton(header, text="↻  Reiniciar app", width=140, height=theme.HEIGHT_INPUT,
                      corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
                      fg_color="transparent", hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB,
                      border_width=1, border_color=theme.BORDER,
                      command=self._restart).pack(side="right")
        ctk.CTkLabel(self, text=f"Los cambios de conexión se aplican al reiniciar · almacén de secretos: {credentials.backend_name()}",
                     font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w").pack(
            anchor="w", padx=theme.SPACE_6, pady=(0, theme.SPACE_2))

        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PAGE,
            segmented_button_fg_color=theme.BG_CARD,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_CARD,
            segmented_button_unselected_hover_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN)
        self.tabs.pack(fill="both", expand=True, padx=theme.SPACE_5, pady=(theme.SPACE_2, theme.SPACE_4))

        self._secret_rows: list[tuple] = []
        self._build_general(self.tabs.add("General"))
        self._build_datos(self.tabs.add("Fuentes de datos"))
        self._build_correo(self.tabs.add("Correo"))
        self._build_ofertas(self.tabs.add("Ofertas"))
        self._build_docusign(self.tabs.add("DocuSign"))
        self._build_ia(self.tabs.add("IA"))
        self._build_usuarios(self.tabs.add("Usuarios"))
        self._resolve_secret_states()

    def _restart(self) -> None:
        if self._on_restart and ui.confirm(self, "Reiniciar", "¿Reiniciar la aplicación para aplicar los cambios?"):
            self._on_restart()

    def _scroll(self, parent) -> ctk.CTkScrollableFrame:
        s = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        s.pack(fill="both", expand=True)
        return s

    # ── reusables ────────────────────────────────────────────────────────────

    def _setting_row(self, parent, label, pref_key, default="", width=260):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=theme.SPACE_1)
        ctk.CTkLabel(row, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", width=170).pack(side="left")
        e = _entry(row, value=str(pref.get(pref_key) or default), width=width)
        e.pack(side="left", fill="x", expand=True)
        return e

    def _secret_row(self, parent, label, secret_key, env_key=None):
        """Fila de credencial. El estado (configurada o no) se resuelve en un
        hilo de fondo: consultar keyring ~10 veces bloqueaba la apertura ~400ms."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=theme.SPACE_1)
        ctk.CTkLabel(row, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", width=170).pack(side="left")
        e = _entry(row, placeholder="comprobando…", show="•")
        e.pack(side="left", fill="x", expand=True)
        state = ctk.CTkLabel(row, text="…", width=20,
                             font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MUTED)
        state.pack(side="left", padx=(theme.SPACE_2, 0))
        self._secret_rows.append((secret_key, env_key, e, state))
        return e, state

    def _resolve_secret_states(self) -> None:
        """Resuelve en background el estado de todas las credenciales y pinta."""
        rows = list(self._secret_rows)

        def work():
            for key, env, entry, state in rows:
                try:
                    ok = credentials.is_set(key, env_fallback=env)
                except Exception:
                    ok = False

                def apply(entry=entry, state=state, ok=ok):
                    try:
                        if not state.winfo_exists():
                            return
                        entry.configure(
                            placeholder_text="•••• (configurada)" if ok else "sin configurar")
                        state.configure(text="✓" if ok else "—",
                                        text_color=theme.GREEN if ok else theme.TEXT_MUTED)
                    except Exception:
                        pass
                self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _save_secret(self, entry, state, secret_key):
        val = entry.get().strip()
        if not val:
            return
        credentials.set(secret_key, val)
        entry.delete(0, "end")
        entry.configure(placeholder_text="•••• (configurada)")
        state.configure(text="✓", text_color=theme.GREEN)
        ui.toast(self, "Guardado", "Credencial almacenada de forma segura.", kind="success")

    # ════════════════════════════════════════════════════════════════════════
    #  GENERAL
    # ════════════════════════════════════════════════════════════════════════

    def _build_general(self, parent) -> None:
        s = self._scroll(parent)
        ui.section_header(s, "Apariencia").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        from core.preferences import get_theme
        row = ctk.CTkFrame(s, fg_color="transparent")
        row.pack(fill="x", pady=theme.SPACE_1)
        ctk.CTkLabel(row, text="Tema actual", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", width=170).pack(side="left")
        ctk.CTkLabel(row, text=get_theme(), font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkButton(row, text="Cambiar tema…", width=130, height=theme.HEIGHT_INPUT,
                      corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color="#FFFFFF",
                      command=self._change_theme).pack(side="right")

        ui.section_header(s, "Comportamiento").pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_2))
        self.ent_refresh = self._setting_row(s, "Auto-refresco (min, 0=off)", "autorefresh_min",
                                             default="5", width=80)
        nrow = ctk.CTkFrame(s, fg_color="transparent")
        nrow.pack(fill="x", pady=theme.SPACE_1)
        ctk.CTkLabel(nrow, text="Notificaciones", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                     anchor="w", width=170).pack(side="left")
        self.sw_notif = ctk.CTkSwitch(nrow, text="", onvalue=True, offvalue=False)
        self.sw_notif.pack(side="left")
        (self.sw_notif.select if pref.get("notifications", True) else self.sw_notif.deselect)()

        ui.section_header(s, "Reclamaciones — Escalado").pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_2))
        ctk.CTkLabel(s, text="Vacío = sin escalado: todas las reclamaciones salen como Recordatorio "
                             "(Nivel 1).\nCuando se definan los plazos con los abogados, indica aquí "
                             "los días para subir de nivel.",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w",
                     justify="left").pack(anchor="w", pady=(0, theme.SPACE_1))
        self.ent_claims_l2 = self._setting_row(s, "Días → Nivel 2 (Formal)", "claims_level2_days",
                                               default="", width=80)
        self.ent_claims_l3 = self._setting_row(s, "Días → Nivel 3 (Urgente)", "claims_level3_days",
                                               default="", width=80)

        ctk.CTkButton(s, text="Guardar comportamiento", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=self._save_general).pack(anchor="w", pady=theme.SPACE_3)

    def _change_theme(self) -> None:
        from gui.widgets.theme_picker import ThemePickerDialog
        from core.preferences import set_theme

        def apply(mode):
            set_theme(mode)
            if self._on_restart:
                self._on_restart()
        ThemePickerDialog(self, on_apply=apply)

    def _save_general(self) -> None:
        try:
            mins = int(self.ent_refresh.get().strip() or "0")
        except ValueError:
            mins = 5
        pref.set_value("autorefresh_min", max(0, mins))
        pref.set_value("notifications", bool(self.sw_notif.get()))
        # Umbrales de escalado de reclamaciones (vacío = desactivado → Nivel 1)
        for ent, key in ((self.ent_claims_l2, "claims_level2_days"),
                         (self.ent_claims_l3, "claims_level3_days")):
            raw = ent.get().strip()
            try:
                pref.set_value(key, int(raw) if raw else "")
            except ValueError:
                pref.set_value(key, "")
        ui.toast(self, "Guardado", "Reinicia para aplicar el auto-refresco.", kind="success")

    # ════════════════════════════════════════════════════════════════════════
    #  FUENTES DE DATOS
    # ════════════════════════════════════════════════════════════════════════

    def _build_datos(self, parent) -> None:
        self.datos_scroll = self._scroll(parent)
        self._render_datos()

    def _render_datos(self) -> None:
        for w in self.datos_scroll.winfo_children():
            w.destroy()
        ui.section_header(self.datos_scroll, "Excels de datos").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        for st in data_source.get_all_status():
            self._datos_card(st)

        ui.section_header(self.datos_scroll, "Carpeta de pedidos (red)").pack(
            fill="x", pady=(theme.SPACE_3, theme.SPACE_2))
        self.ent_pedidos = self._setting_row(self.datos_scroll, "Ruta base (M:\\…)",
                                             "pedidos_base_path", width=360)
        ctk.CTkButton(self.datos_scroll, text="Guardar ruta", height=34, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF",
                      command=lambda: (pref.set_value("pedidos_base_path", self.ent_pedidos.get().strip()),
                                       ui.toast(self, "Guardado", "Reinicia para aplicar.", kind="success"))
                      ).pack(anchor="w", pady=theme.SPACE_2)

    def _datos_card(self, st: dict) -> None:
        card = ctk.CTkFrame(self.datos_scroll, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_2))
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 0))
        ctk.CTkLabel(top, text=st["label"], font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        col = theme.GREEN if st["exists"] else theme.RED
        ctk.CTkLabel(top, text=("● " + st["mode"]) if st["exists"] else "● no encontrado",
                     font=theme.FONT_TINY, text_color=col).pack(side="right")
        ctk.CTkLabel(card, text=st["path"], font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                     anchor="w", wraplength=760).pack(fill="x", padx=theme.SPACE_3)
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
        k = st["kind"]
        ctk.CTkButton(btns, text="Importar", width=90, height=28, corner_radius=theme.RADIUS_SM,
                      font=theme.FONT_TINY, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=lambda: self._datos_import(k)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="Vincular ruta", width=110, height=28, corner_radius=theme.RADIUS_SM,
                      font=theme.FONT_TINY, fg_color="transparent", hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                      command=lambda: self._datos_link(k)).pack(side="left", padx=(0, 6))
        if st.get("linked_path"):
            ctk.CTkButton(btns, text="Quitar vínculo", width=110, height=28, corner_radius=theme.RADIUS_SM,
                          font=theme.FONT_TINY, fg_color="transparent", hover_color=theme.BG_INPUT,
                          text_color=theme.TEXT_MUTED, border_width=1, border_color=theme.BORDER,
                          command=lambda: (data_source.clear_link(k), self._render_datos())).pack(side="left")

    def _datos_import(self, kind: str) -> None:
        path = filedialog.askopenfilename(parent=self, title=f"Importar {kind}",
                                          filetypes=[("Excel", "*.xlsx *.xlsm")])
        if not path:
            return
        try:
            data_source.import_file(kind, path)
            ui.toast(self, "Importado", data_source.label(kind), kind="success")
            self._render_datos()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _datos_link(self, kind: str) -> None:
        path = filedialog.askopenfilename(parent=self, title=f"Vincular {kind}",
                                          filetypes=[("Excel", "*.xlsx *.xlsm")])
        if not path:
            return
        try:
            data_source.set_linked_path(kind, path)
            ui.toast(self, "Vinculado", data_source.label(kind), kind="success")
            self._render_datos()
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    # ════════════════════════════════════════════════════════════════════════
    #  CORREO / OFERTAS / DOCUSIGN / IA
    # ════════════════════════════════════════════════════════════════════════

    def _build_correo(self, parent) -> None:
        s = self._scroll(parent)
        ui.section_header(s, "IMAP (lectura)").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        self.imap_host = self._setting_row(s, "Host", "imap_host", "imap.soljem.com")
        self.imap_port = self._setting_row(s, "Puerto", "imap_port", "993", width=80)
        self.imap_user = self._setting_row(s, "Usuario", "imap_user", "documentacion@eipsa.es")
        self.imap_pass, self.imap_pass_state = self._secret_row(s, "Contraseña", "imap_pass", "IMAP_PASS")

        ui.section_header(s, "SMTP (envío)").pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_2))
        self.smtp_host = self._setting_row(s, "Host", "smtp_host", "smtp.soljem.com")
        self.smtp_port = self._setting_row(s, "Puerto", "smtp_port", "465", width=80)
        self.smtp_user = self._setting_row(s, "Usuario", "smtp_user", "documentacion@eipsa.es")
        self.smtp_pass, self.smtp_pass_state = self._secret_row(s, "Contraseña", "smtp_pass", "SMTP_PASS")

        btns = ctk.CTkFrame(s, fg_color="transparent")
        btns.pack(anchor="w", pady=theme.SPACE_3)
        ctk.CTkButton(btns, text="Guardar correo", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=self._save_correo).pack(side="left", padx=(0, theme.SPACE_2))
        ctk.CTkButton(btns, text="Probar IMAP", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color="transparent", hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                      command=self._test_imap).pack(side="left", padx=(0, theme.SPACE_2))
        ctk.CTkButton(btns, text="Probar SMTP", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color="transparent", hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                      command=self._test_smtp).pack(side="left")

    def _save_correo(self) -> None:
        for key, ent in [("imap_host", self.imap_host), ("imap_port", self.imap_port),
                         ("imap_user", self.imap_user), ("smtp_host", self.smtp_host),
                         ("smtp_port", self.smtp_port), ("smtp_user", self.smtp_user)]:
            pref.set_value(key, ent.get().strip())
        self._save_secret(self.imap_pass, self.imap_pass_state, "imap_pass")
        self._save_secret(self.smtp_pass, self.smtp_pass_state, "smtp_pass")
        ui.toast(self, "Guardado", "Correo configurado. Reinicia para aplicar.", kind="success")

    def _test_imap(self) -> None:
        host = self.imap_host.get().strip(); port = int(self.imap_port.get().strip() or "993")
        user = self.imap_user.get().strip()
        pw = self.imap_pass.get().strip() or credentials.get("imap_pass", "IMAP_PASS")

        def work():
            try:
                import imaplib
                c = imaplib.IMAP4_SSL(host, port); c.login(user, pw); c.logout()
                self.after(0, lambda: ui.toast(self, "IMAP OK", f"Conexión correcta con {user}", kind="success"))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: ui.toast(self, "IMAP error", msg, kind="error"))
        threading.Thread(target=work, daemon=True).start()

    def _test_smtp(self) -> None:
        host = self.smtp_host.get().strip(); port = int(self.smtp_port.get().strip() or "465")
        user = self.smtp_user.get().strip()
        pw = self.smtp_pass.get().strip() or credentials.get("smtp_pass", "SMTP_PASS")

        def work():
            try:
                import smtplib
                s = smtplib.SMTP_SSL(host, port, timeout=10); s.login(user, pw); s.quit()
                self.after(0, lambda: ui.toast(self, "SMTP OK", f"Conexión correcta con {user}", kind="success"))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: ui.toast(self, "SMTP error", msg, kind="error"))
        threading.Thread(target=work, daemon=True).start()

    def _build_ofertas(self, parent) -> None:
        s = self._scroll(parent)
        keys = [("Comercial", "ofertas_comercial_user", "ofertas_comercial_pass", "OFERTAS_COMERCIAL_PASS"),
                ("Dpto. Comercial", "ofertas_dpto_user", "ofertas_dpto_pass", "OFERTAS_DPTO_PASS"),
                ("Info", "ofertas_info_user", "ofertas_info_pass", "OFERTAS_INFO_PASS")]
        self._ofertas_fields = []
        defaults = {a["label"]: a["user"] for a in OFERTAS_ACCOUNTS}
        for label, ukey, pkey, env in keys:
            ui.section_header(s, f"Buzón · {label}").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_1))
            ue = self._setting_row(s, "Usuario", ukey, defaults.get(label, ""))
            pe, ps = self._secret_row(s, "Contraseña", pkey, env)
            self._ofertas_fields.append((ukey, ue, pkey, pe, ps))
        ctk.CTkButton(s, text="Guardar buzones", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=self._save_ofertas).pack(anchor="w", pady=theme.SPACE_3)

        # ── Seguimiento de respuestas de comerciales (opt-in) ────────────────
        ui.section_header(s, "Seguimiento de comerciales (opt-in)").pack(
            fill="x", pady=(theme.SPACE_4, theme.SPACE_1))
        ctk.CTkLabel(
            s, text=("Permite saber si una oferta se respondió desde el correo de un comercial.\n"
                     "SOLO LECTURA: lee únicamente su carpeta «Enviados» (cabeceras), nunca marca, "
                     "mueve ni borra nada. Requiere informar y contar con su consentimiento."),
            font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w", justify="left").pack(
            anchor="w", pady=(0, theme.SPACE_2))

        self.track_list = ctk.CTkFrame(s, fg_color="transparent")
        self.track_list.pack(fill="x")
        self._render_tracked()

        addbox = ctk.CTkFrame(s, fg_color=theme.BG_CARD, corner_radius=8,
                              border_width=1, border_color=theme.BORDER)
        addbox.pack(fill="x", pady=theme.SPACE_2)
        row = ctk.CTkFrame(addbox, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_3)
        self.trk_label = _entry(row, placeholder="Nombre (ej: Ana Calvo)", width=160)
        self.trk_label.pack(side="left", padx=(0, theme.SPACE_2))
        self.trk_user = _entry(row, placeholder="correo@eipsa.es", width=200)
        self.trk_user.pack(side="left", padx=(0, theme.SPACE_2))
        self.trk_pass = _entry(row, placeholder="contraseña", show="•")
        self.trk_pass.pack(side="left", fill="x", expand=True, padx=(0, theme.SPACE_2))
        ctk.CTkButton(row, text="+ Añadir", width=90, height=theme.HEIGHT_INPUT,
                      corner_radius=theme.RADIUS_MD, font=theme.FONT_SMALL_BOLD,
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color="#FFFFFF",
                      command=self._add_tracked).pack(side="left")

    def _render_tracked(self) -> None:
        from core.services import ofertas as ofsvc
        for w in self.track_list.winfo_children():
            w.destroy()
        mboxes = ofsvc.list_tracked_mailboxes()
        if not mboxes:
            ctk.CTkLabel(self.track_list, text="Sin buzones de seguimiento configurados.",
                         font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
            return
        for mb in mboxes:
            r = ctk.CTkFrame(self.track_list, fg_color=theme.BG_CARD, corner_radius=8,
                             border_width=1, border_color=theme.BORDER)
            r.pack(fill="x", pady=(0, theme.SPACE_1))
            inner = ctk.CTkFrame(r, fg_color="transparent")
            inner.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
            ctk.CTkLabel(inner, text=f"📤 {mb.get('label') or mb['user']}", font=theme.FONT_SMALL_BOLD,
                         text_color=theme.TEXT_MAIN).pack(side="left")
            ctk.CTkLabel(inner, text=mb["user"], font=theme.FONT_TINY,
                         text_color=theme.TEXT_MUTED).pack(side="left", padx=(theme.SPACE_2, 0))
            ctk.CTkButton(inner, text="Quitar", width=70, height=26, corner_radius=theme.RADIUS_SM,
                          font=theme.FONT_TINY, fg_color="transparent", hover_color=theme.BG_INPUT,
                          text_color=theme.RED, border_width=1, border_color=theme.RED,
                          command=lambda u=mb["user"]: self._remove_tracked(u)).pack(side="right")

    def _add_tracked(self) -> None:
        from core.services import ofertas as ofsvc
        user = self.trk_user.get().strip()
        pw = self.trk_pass.get().strip()
        if not user or not pw:
            messagebox.showwarning("Seguimiento", "Indica correo y contraseña del comercial.", parent=self)
            return
        if not ui.confirm(self, "Confirmar acceso",
                          f"¿Confirmas que {user} ha sido informado y autoriza el seguimiento "
                          "de su carpeta Enviados (solo lectura)?"):
            return
        ofsvc.add_tracked_mailbox(self.trk_label.get().strip(), user, pw)
        for e in (self.trk_label, self.trk_user, self.trk_pass):
            e.delete(0, "end")
        ui.toast(self, "Añadido", f"Seguimiento de {user} configurado.", kind="success")
        self._render_tracked()

    def _remove_tracked(self, user: str) -> None:
        from core.services import ofertas as ofsvc
        ofsvc.remove_tracked_mailbox(user)
        ui.toast(self, "Quitado", f"Seguimiento de {user} eliminado.", kind="success")
        self._render_tracked()

    def _save_ofertas(self) -> None:
        for ukey, ue, pkey, pe, ps in self._ofertas_fields:
            pref.set_value(ukey, ue.get().strip())
            self._save_secret(pe, ps, pkey)
        ui.toast(self, "Guardado", "Buzones de ofertas configurados. Reinicia para aplicar.", kind="success")

    def _build_docusign(self, parent) -> None:
        s = self._scroll(parent)
        ui.section_header(s, "DocuSign eSignature").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        ctk.CTkLabel(s, text=("● Conectado / configurado" if ds.is_configured() else "● No configurado"),
                     font=theme.FONT_SMALL_BOLD,
                     text_color=theme.GREEN if ds.is_configured() else theme.AMBER,
                     anchor="w").pack(anchor="w", pady=(0, theme.SPACE_2))
        self.ds_ik, self.ds_ik_s = self._secret_row(s, "Integration Key", "docusign_integration_key", "DOCUSIGN_INTEGRATION_KEY")
        self.ds_uid, self.ds_uid_s = self._secret_row(s, "User ID", "docusign_user_id", "DOCUSIGN_USER_ID")
        self.ds_aid, self.ds_aid_s = self._secret_row(s, "Account ID", "docusign_account_id", "DOCUSIGN_ACCOUNT_ID")
        self.ds_url = self._setting_row(s, "Base URL", "docusign_base_url", "https://demo.docusign.net", width=320)
        self.ds_pem = self._setting_row(s, "Ruta clave RSA (.pem)", "docusign_rsa_path", "docusign_private.pem", width=320)
        ctk.CTkButton(s, text="Guardar DocuSign", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=self._save_docusign).pack(anchor="w", pady=theme.SPACE_3)

    def _save_docusign(self) -> None:
        self._save_secret(self.ds_ik, self.ds_ik_s, "docusign_integration_key")
        self._save_secret(self.ds_uid, self.ds_uid_s, "docusign_user_id")
        self._save_secret(self.ds_aid, self.ds_aid_s, "docusign_account_id")
        pref.set_value("docusign_base_url", self.ds_url.get().strip())
        pref.set_value("docusign_rsa_path", self.ds_pem.get().strip())
        ui.toast(self, "Guardado", "DocuSign configurado. Reinicia para aplicar.", kind="success")

    def _build_ia(self, parent) -> None:
        s = self._scroll(parent)
        ui.section_header(s, "Anthropic (Claude)").pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_2))
        self.ia_key, self.ia_key_s = self._secret_row(s, "API Key", "anthropic_api_key", "ANTHROPIC_API_KEY")
        ctk.CTkButton(s, text="Guardar API Key", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF",
                      command=lambda: self._save_secret(self.ia_key, self.ia_key_s, "anthropic_api_key")).pack(
            anchor="w", pady=theme.SPACE_3)

        ui.section_header(s, "Migración de credenciales").pack(fill="x", pady=(theme.SPACE_4, theme.SPACE_2))
        ctk.CTkLabel(s, text="Mueve las credenciales que aún estén en .env al almacén seguro.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        ctk.CTkButton(s, text="Importar credenciales del .env", height=36, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color="transparent", hover_color=theme.BG_INPUT,
                      text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                      command=self._migrate_env).pack(anchor="w", pady=theme.SPACE_2)

    def _migrate_env(self) -> None:
        import os
        moved = 0
        for skey, env in SECRET_ENV_MAP.items():
            if not credentials.is_set(skey) and os.getenv(env):
                credentials.set(skey, os.getenv(env))
                moved += 1
        ui.toast(self, "Migración", f"{moved} credencial(es) movida(s) al almacén seguro.",
                 kind="success" if moved else "info")

    # ════════════════════════════════════════════════════════════════════════
    #  USUARIOS
    # ════════════════════════════════════════════════════════════════════════

    def _build_usuarios(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(fill="x", pady=(theme.SPACE_2, theme.SPACE_1))
        ctk.CTkLabel(bar, text="Cuentas y permisos por sección", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ctk.CTkButton(bar, text="+ Nuevo usuario", height=32, corner_radius=theme.RADIUS_MD,
                      font=theme.FONT_SMALL_BOLD, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color="#FFFFFF", command=lambda: self._edit_user(None)).pack(side="right")
        self.users_scroll = self._scroll(parent)
        self._render_users()

    def _render_users(self) -> None:
        for w in self.users_scroll.winfo_children():
            w.destroy()
        for u in auth.list_users():
            self._user_card(u)

    def _user_card(self, u: dict) -> None:
        card = ctk.CTkFrame(self.users_scroll, fg_color=theme.BG_CARD, corner_radius=10,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, theme.SPACE_2))
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)
        col = ui.avatar_color(u["initials"])
        av = ctk.CTkFrame(top, width=32, height=32, corner_radius=16, fg_color=col)
        av.pack(side="left", padx=(0, theme.SPACE_2)); av.pack_propagate(False)
        ctk.CTkLabel(av, text=u["initials"], font=theme.font(11, "bold"), text_color="#FFFFFF").pack(expand=True)
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        admin = u.get("is_admin")
        ctk.CTkLabel(info, text=u["nombre"] + ("  · admin" if admin else ""),
                     font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
        if not admin:
            gestion = [k for k, v in (u.get("permisos") or {}).items() if v == "gestionar"]
            ver = [k for k, v in (u.get("permisos") or {}).items() if v == "ver"]
            ctk.CTkLabel(info, text=f"Gestiona {len(gestion)} · Ve {len(ver)} sección(es)",
                         font=theme.FONT_TINY, text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        if not admin:
            ctk.CTkButton(top, text="Editar", width=70, height=28, corner_radius=theme.RADIUS_SM,
                          font=theme.FONT_TINY, fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
                          text_color=theme.TEXT_SUB, command=lambda: self._edit_user(u)).pack(side="right", padx=(4, 0))
            ctk.CTkButton(top, text="Reset clave", width=90, height=28, corner_radius=theme.RADIUS_SM,
                          font=theme.FONT_TINY, fg_color=theme.BG_INPUT, hover_color=theme.BORDER,
                          text_color=theme.TEXT_SUB, command=lambda: self._reset_pwd(u)).pack(side="right", padx=(4, 0))
            ctk.CTkButton(top, text="Eliminar", width=80, height=28, corner_radius=theme.RADIUS_SM,
                          font=theme.FONT_TINY, fg_color="transparent", hover_color=theme.BG_INPUT,
                          text_color=theme.RED, border_width=1, border_color=theme.RED,
                          command=lambda: self._delete_user(u)).pack(side="right", padx=(4, 0))

    def _reset_pwd(self, u: dict) -> None:
        UserPasswordDialog(self, u, on_done=self._render_users)

    def _delete_user(self, u: dict) -> None:
        if ui.confirm(self, "Eliminar usuario", f"¿Eliminar la cuenta de {u['nombre']} ({u['initials']})?"):
            ok, err = auth.delete_user(u["initials"])
            if ok:
                ui.toast(self, "Eliminado", u["initials"], kind="success")
                self._render_users()
            else:
                messagebox.showerror("Error", err, parent=self)

    def _edit_user(self, u):
        UserEditDialog(self, u, on_done=self._render_users)


# ════════════════════════════════════════════════════════════════════════════
#  Diálogos de usuario
# ════════════════════════════════════════════════════════════════════════════

class UserEditDialog(ctk.CTkToplevel):
    def __init__(self, master, user, on_done=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self._user = user
        self._on_done = on_done
        self._new = user is None
        self.title("Nuevo usuario" if self._new else f"Editar {user['initials']}")
        self.geometry("520x640")
        self.transient(master); self.grab_set()
        self._build()

    def _build(self) -> None:
        pad = 20
        ctk.CTkLabel(self, text="Nuevo usuario" if self._new else f"Editar · {self._user['initials']}",
                     font=theme.font(16, "bold"), text_color=theme.TEXT_MAIN).pack(anchor="w", padx=pad, pady=(18, 8))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=pad)
        self.e_ini = _entry(form, value="" if self._new else self._user["initials"], placeholder="Iniciales (ej: AC)")
        self.e_nombre = _entry(form, value="" if self._new else self._user.get("nombre", ""), placeholder="Nombre")
        self.e_email = _entry(form, value="" if self._new else self._user.get("email", ""), placeholder="Email (opcional)")
        for lbl, e in [("Iniciales", self.e_ini), ("Nombre", self.e_nombre), ("Email", self.e_email)]:
            r = ctk.CTkFrame(form, fg_color="transparent"); r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=lbl, width=90, anchor="w", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB).pack(side="left")
            e.pack(side="left", fill="x", expand=True)
        if self._new:
            self.e_ini.configure(state="normal")
            r = ctk.CTkFrame(form, fg_color="transparent"); r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text="Contraseña", width=90, anchor="w", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_SUB).pack(side="left")
            self.e_pwd = _entry(r, placeholder="(por defecto Aa123456)", show="•")
            self.e_pwd.pack(side="left", fill="x", expand=True)
        else:
            self.e_ini.configure(state="disabled")

        ui.section_header(self, "Permisos por sección").pack(fill="x", padx=pad, pady=(theme.SPACE_3, theme.SPACE_1))
        grid = ctk.CTkScrollableFrame(self, fg_color="transparent", height=300)
        grid.pack(fill="both", expand=True, padx=pad, pady=(0, 8))
        self._perm_vars = {}
        cur = (self._user or {}).get("permisos") or {}
        for key in auth.SECTION_KEYS:
            row = ctk.CTkFrame(grid, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=key.capitalize(), width=160, anchor="w", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MAIN).pack(side="left")
            var = ctk.StringVar(value=cur.get(key, "ver"))
            ctk.CTkOptionMenu(row, values=["none", "ver", "gestionar"], variable=var, width=130,
                              height=28, font=theme.FONT_TINY, fg_color=theme.BG_INPUT,
                              button_color=theme.BORDER_STRONG, button_hover_color=theme.TEXT_MUTED,
                              text_color=theme.TEXT_MAIN).pack(side="right")
            self._perm_vars[key] = var

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=pad, pady=(0, 14))
        ctk.CTkButton(foot, text="Cancelar", height=36, corner_radius=8, fg_color=theme.BG_CARD,
                      hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB, border_width=1,
                      border_color=theme.BORDER, command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(foot, text="Guardar", height=36, corner_radius=8, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color="#FFFFFF", font=theme.FONT_SMALL_BOLD,
                      command=self._save).pack(side="right")

    def _save(self) -> None:
        permisos = {k: v.get() for k, v in self._perm_vars.items()}
        if self._new:
            ok, err = auth.create_user(self.e_ini.get(), self.e_nombre.get(), self.e_email.get(),
                                       password=self.e_pwd.get().strip() or None, permisos=permisos)
        else:
            ok, err = auth.update_user(self._user["initials"], nombre=self.e_nombre.get(),
                                       email=self.e_email.get(), permisos=permisos)
        if not ok:
            messagebox.showerror("Error", err, parent=self)
            return
        ui.toast(self.master, "Guardado", "Usuario actualizado.", kind="success")
        if self._on_done:
            self._on_done()
        self.destroy()


class UserPasswordDialog(ctk.CTkToplevel):
    def __init__(self, master, user, on_done=None):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self._user = user
        self._on_done = on_done
        self.title(f"Reset contraseña · {user['initials']}")
        self.geometry("420x200")
        self.transient(master); self.grab_set()
        ctk.CTkLabel(self, text=f"Nueva contraseña para {user['nombre']}", font=theme.font(14, "bold"),
                     text_color=theme.TEXT_MAIN).pack(anchor="w", padx=20, pady=(20, 10))
        self.e = _entry(self, placeholder="mínimo 6 caracteres", show="•")
        self.e.pack(fill="x", padx=20)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=20, pady=20)
        ctk.CTkButton(foot, text="Cancelar", height=36, corner_radius=8, fg_color=theme.BG_CARD,
                      hover_color=theme.BG_INPUT, text_color=theme.TEXT_SUB, border_width=1,
                      border_color=theme.BORDER, command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(foot, text="Guardar", height=36, corner_radius=8, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color="#FFFFFF", font=theme.FONT_SMALL_BOLD,
                      command=self._save).pack(side="right")

    def _save(self) -> None:
        ok, err = auth.reset_password(self._user["initials"], self.e.get().strip())
        if not ok:
            messagebox.showerror("Error", err, parent=self)
            return
        ui.toast(self.master, "Contraseña actualizada",
                 f"{self._user['initials']} deberá cambiarla al entrar.", kind="success")
        if self._on_done:
            self._on_done()
        self.destroy()
