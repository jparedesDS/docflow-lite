"""Configuración global — IMAP/SMTP, paths y mapeos de equipo."""

import logging
import os

from dotenv import load_dotenv

from core.paths import app_root, data_dir, state_dir

# Cargar .env desde la raíz del proyecto si existe
load_dotenv(app_root() / ".env")

logger = logging.getLogger(__name__)

# ── Rutas a Excels ────────────────────────────────────────────────────────────
DATA_ERP_PATH = os.getenv("DATA_ERP_PATH") or str(data_dir() / "data_erp.xlsx")
CONSULTA_ERP_PATH = os.getenv("CONSULTA_ERP_PATH") or str(data_dir() / "consulta_erp.xlsx")
TAGS_PATH = os.getenv("TAGS_PATH") or str(data_dir() / "data_tags.xlsx")

# ── IMAP ──────────────────────────────────────────────────────────────────────
IMAP_HOST = os.getenv("IMAP_HOST", "imap.soljem.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "documentacion@eipsa.es")
IMAP_PASS = os.getenv("IMAP_PASS", "")

# ── SMTP ──────────────────────────────────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.soljem.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "documentacion@eipsa.es")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# ── Anthropic (Claude) — para Bandeja AI y otros asistentes ───────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Estado runtime ────────────────────────────────────────────────────────────
PROCESSED_EMAILS_FILE = str(state_dir() / "processed_emails.json")

# ── Carpeta de pedidos en red (opcional, para guardar EML enviados) ───────────
PEDIDOS_BASE_PATH = os.getenv("PEDIDOS_BASE_PATH", "")

# ── Equipo EIPSA ──────────────────────────────────────────────────────────────
USERS = {
    "JP":  {"nombre": "Jose Paredes",      "emails": ["documentacion@eipsa.es", "jose-paredes@eipsa.es"]},
    "AC":  {"nombre": "Ana Calvo",         "emails": ["ana-calvo@eipsa.es"]},
    "JM":  {"nombre": "Jesus Martinez",    "emails": ["jesus-martinez@eipsa.es"]},
    "EC":  {"nombre": "Ernesto Carrillo",  "emails": ["ernesto-carrillo@eipsa.es"]},
    "LB":  {"nombre": "Luis Bravo",        "emails": ["luis-bravo@eipsa.es"]},
    "SS":  {"nombre": "Santos Sanchez",    "emails": ["santos-sanchez@eipsa.es"]},
    "JV":  {"nombre": "Jorge Valtierra",   "emails": ["jorge-valtierra@eipsa.es"]},
    "CCH": {"nombre": "Carlos Crespo",     "emails": ["carlos-crespohor@eipsa.es"]},
    "LM":  {"nombre": "Laura Minguez",     "emails": ["laura-minguez@eipsa.es"]},
    "DM":  {"nombre": "Daniel Marquez",    "emails": ["daniel-marquez@eipsa.es"]},
    "MS":  {"nombre": "Miguel Sahuquillo", "emails": ["miguel-sahuquillo@eipsa.es"]},
    "ES":  {"nombre": "Enrique Serrano",   "emails": ["enrique-serrano@eipsa.es"]},
    "JZ":  {"nombre": "Javier Zofio",      "emails": ["javier-zofio@eipsa.es"]},
    "JS":  {"nombre": "Jose A. Sanz",      "emails": ["josea-sanz@eipsa.es"]},
    "JUZ": {"nombre": "Julio Zofio",       "emails": ["julio-zofio@eipsa.es"]},
    "CZ":  {"nombre": "Carolina Zofio",    "emails": ["carolina-zofio@eipsa.es"]},
    "ALM": {"nombre": "Almacen",           "emails": ["almacen@eipsa.es"]},
    "MG":  {"nombre": "Mario Gil",         "emails": ["mario-gil@eipsa.es"]},
    "JUM": {"nombre": "Julian Martinez",   "emails": ["julian-martinez@eipsa.es"]},
    "RM":  {"nombre": "Rosa Martin",       "emails": ["rosa-martin@eipsa.es"]},
}


def startup_warnings():
    """Avisar de configuración mínima ausente al arrancar."""
    if not SMTP_PASS:
        logger.warning("SMTP_PASS vacío — el envío de emails fallará")
    if not IMAP_PASS:
        logger.warning("IMAP_PASS vacío — la lectura de emails fallará")
    if not os.path.exists(DATA_ERP_PATH):
        logger.warning("data_erp.xlsx no encontrado en %s — tracking no funcionará", DATA_ERP_PATH)
