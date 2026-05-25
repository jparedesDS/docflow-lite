import re
import pandas as pd
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════════
#  MAPPINGS COMPARTIDOS (migrados de DocuControl)
# ═══════════════════════════════════════════════════════

# PO → Nº Pedido (PRODOC/ACONEX)
PRODOC_PO_MAP = {
    "7011318362": "P-24/091", "7070000087": "P-24/054",
    "7011319592": "P-24/073", "7011294464": "P-23/087",
    "600017293": "P-23/097", "7011265051": "P-24/006",
    "7080111164": "P-24/023", "7080113517": "P-24/044",
    "7011295889": "P-24/050", "7080115423": "P-24/058",
    "7080115700": "P-24/060",
}

# PO → Nº Pedido (SENDOC)
SENDOC_PO_MAP = {
    "P1Q2700002-PF-V": "P-25/009-S00",
}

# Package → Nº Pedido (ACONEX)
ACONEX_PO_MAP = {
    "2201BI01A0-2206-3000": "P-25/037",
}

# Project key → Nº Pedido (DOCUMENT SPACE / HEC)
DOCSPACE_PO_MAP = {
    "JUS&ICS2": "P-24/070",
}
DOCSPACE_SUPP_MAP = {
    "JUS&ICS2": "S00",
}
DOCSPACE_MATERIAL_MAP = {
    "JUS&ICS2": "CAUDAL",
}

# PO → Material
PRODOC_MATERIAL_MAP = {
    "7011318362": "CAUDAL", "7070000087": "TEMPERATURA",
    "7011319592": "TEMPERATURA", "7011294464": "PLACAS",
}

SENDOC_MATERIAL_MAP = {
    "P1Q2700002-PF-V": "TEMPERATURA",
}

GAIA_MATERIAL_MAP = {
    "214726C": "CAUDAL", "7070000087": "TEMPERATURA",
}

# Doc type code → Nombre español
DOC_TYPE_MAP = {
    "PLG": "Planos", "DWG": "Planos", "DRAWINGS": "Planos",
    "CAL": "Cálculos", "ESP": "Cálculos y Planos",
    "CER": "Certificado", "NACE": "Certificado",
    "DOS": "Dossier", "DD": "Dossier",
    "LIS": "Listado", "LIST": "Listado", "VDB": "Listado",
    "VDDL": "Listado", "DL": "Listado",
    "ITP": "PPI", "PLN": "PPI",
    "PRC": "Procedimientos", "NDE": "Procedimientos", "PH": "Procedimientos",
    "MAN": "Manual", "PLD": "Nameplate",
    "CAT": "Catalogo", "SPL": "Repuestos",
    "WD": "Soldadura", "IND": "Indice",
}

# Tipo doc → Crítico
CRITICO_MAP = {
    "Planos": "Sí", "Cálculos": "Sí", "Cálculos y Planos": "Sí",
    "Manual": "Sí", "PPI": "Sí", "Catalogo": "Sí", "Listado": "Sí",
    "Certificado": "No", "Dossier": "No", "Procedimientos": "No",
    "Nameplate": "No", "Repuestos": "No", "Indice": "No",
    "Soldadura": "No",
}

# Status mappings por plataforma
ACONEX_STATUS_MAP = {
    "A - REJECTED": "Rechazado",
    "1 - WITH COMMENTS": "Com. Mayores",
    "2 - WITHOUT COMMENTS": "Aprobado",
    "2I - FOR INFORMATION ONLY": "Informativo",
    "3 - WITH MINOR COMMENTS": "Com. Menores",
}

SENDOC_STATUS_MAP = {
    "(COD 5)": "Rechazado",
    "2-REVIEW WITH COMMENTS (COD 2)": "Com. Menores",
    "1-NO COMMENTS (COD 1)": "Aprobado",
    "(COD 3)": "Com. Mayores",
    "4-INF ONLY (COD 4)": "Informativo",
}

GAIA_STATUS_MAP = {
    "Code 1": "Com. Mayores",
    "Code 2": "Com. Menores",
    "Code 3": "Aprobado",
    "Code 4": "Informativo",
    "Code 5": "Rechazado",
}

# PO (primeros 5 chars) → Cliente
PO_CLIENT_MAP = {
    '21472': 'TECHNIP/SYNKEDIA',
    '10121': 'DUQM', '10150': 'BAPCO',
    '10160': 'CRISP', '10230': 'MARJAN',
    '10318': 'RAS TANURA', '10330': 'NEW PTA COMPLEX',
    '10370': 'QATAR EPC3', '10380': 'YPF',
    '10400': 'ADNOC DALMA', '10430': 'QATAR EPC4',
    '23222': 'CQP', '23262': 'Certificado',
    '33138': 'DUQM', '70150': 'SEWA',
    '70215': 'CFE MERIDA', '70225': 'C.C. VALLADOLID',
    '70230': 'C.C. GONZALEZ ORTEGA', '70240': 'C.C. SAN LUIS',
    '80057': 'BU HASA', '80091': 'T.R. ENAP',
    '19085': 'CEPSA/T.R.', '30011': 'BP OIL ESPAÑA',
    '75001': 'TECNIMONT', '60001': 'CEPSA WOOD',
    '70112': 'CEPSA SAN ROQUE', '70801': 'CEPSA',
    '15282': 'ASTCOR', 'T.206': 'REPSOL PETRÓLEO',
    'BP-T2': 'CNTCC', 'EP24I': 'ALMARAZ/TRILLO',
    '49000': 'JIGPC/ARAMCO', 'PO 15': 'ASTCOR',
    'Q3710': 'INTECSA INDUSTRIAL', 'RFQ 1': 'BU HASA',
    '70292': 'LECTA', 'APEIS': 'KNPC',
    '30012': 'BP OIL REFINERIA',
    'EC24T': 'ALMARAZ/TRILLO', '10735': 'SULZER',
    '70700': 'CEPSA/WOOD', 'JUS&I': 'ARAMCO/HYUNDAI',
    '70113': 'CEPSA', '10620': 'QATARBOP/TR',
    'ADI-2': 'TECHNIP/SYNKEDIA', '10431': 'QATAREPC4/TR',
    'PO P7': 'TECHNIP/REPSOL', '12574': 'ALPARGATA',
    '23000': 'TECHNIP/GALP',
    '45077': 'ARAMCO PORTAL', '45000': 'AYESA/REPSOL',
    '30015': 'BP OIL ESPAÑA', '19162': 'WISON/ARAMCO',
    '48550': 'WISON/ARAMCO', '20175': 'TECHNIP/REPSOL',
    'QR-DD': 'ASTCOR/WOOD', 'RFPP-': 'IDOM/REPSOL',
    '10120': 'TR/DUQM', 'SOCAR': 'SOCAR/EMERSON',
    '41650': 'SOCAR/EMERSON', 'P-P0C': 'SACYR/REPSOL',
    'SEG/B': 'SINOPEC/ARAMCO', 'SEG /': 'SINOPEC/ARAMCO',
    '10651': 'ARAMCO/RIYAS', '45124': 'ADNOC/YOKOGAWA',
    'O-23/': 'SINES/YOKOGAWA', 'O-24/': 'SENER/GATE',
    'GAT22': 'SENER/GATE', '45126': 'ADNOC/YOKOGAWA',
    'POPRI': 'REPSOL', '06000': 'CEPSA', '5040-': 'MEDGAZ',
    'PO 45': 'ARAMCO', 'E2404': 'SENYANG', '5061-': 'MEDGAZ',
    '60002': 'MOEVE', 'TR-19': 'MOEVE', '19128': 'MOEVE',
    'D2632': 'MOEVE', '44000': 'PETRONASH',
    'PE-47': 'TECMACO', '45131': 'YOKOWAGA/GALP', 'EC25T': 'ALMARAZ/TRILLO',
    '45032': 'YARA', '46000': 'JIGPC', '30013': 'BP/TECHNIP',
    '19116': 'BP OIL',
    '2201B': 'ACONEX',
}

# Emails de responsables
_EMAIL_LB = 'luis-bravo@eipsa.es'
_EMAIL_AC = 'ana-calvo@eipsa.es'
_EMAIL_SS = 'luis-bravo@eipsa.es'  # En DocuControl email_SS apunta a luis-bravo
_EMAIL_JV = 'jorge-valtierra@eipsa.es'
_EMAIL_CCH = 'carlos-crespohor@eipsa.es'

# Nº Pedido → email responsable proyecto
RESPONSABLE_PEDIDO_MAP = {
    'P-21/003': _EMAIL_LB,
    'P-22/001': _EMAIL_LB, 'P-22/002': _EMAIL_LB, 'P-22/003': _EMAIL_AC, 'P-22/004': _EMAIL_AC,
    'P-22/005': _EMAIL_AC, 'P-22/006': _EMAIL_LB, 'P-22/007': _EMAIL_LB, 'P-22/008': _EMAIL_AC,
    'P-22/009': _EMAIL_LB, 'P-22/010': _EMAIL_AC, 'P-22/011': _EMAIL_LB, 'P-22/012': _EMAIL_AC,
    'P-22/013': _EMAIL_LB, 'P-22/014': _EMAIL_AC, 'P-22/015': _EMAIL_LB, 'P-22/016': _EMAIL_LB,
    'P-22/017': _EMAIL_AC, 'P-22/018': _EMAIL_AC, 'P-22/019': _EMAIL_AC, 'P-22/020': _EMAIL_LB,
    'P-22/021': _EMAIL_AC, 'P-22/022': _EMAIL_AC, 'P-22/023': _EMAIL_AC, 'P-22/024': _EMAIL_AC,
    'P-22/025': _EMAIL_LB, 'P-22/026': _EMAIL_LB, 'P-22/027': _EMAIL_LB, 'P-22/028': _EMAIL_AC,
    'P-22/029': _EMAIL_LB, 'P-22/030': _EMAIL_LB, 'P-22/031': _EMAIL_AC, 'P-22/032': _EMAIL_AC,
    'P-22/033': _EMAIL_LB, 'P-22/034': _EMAIL_LB, 'P-22/035': _EMAIL_AC, 'P-22/036': _EMAIL_AC,
    'P-22/037': _EMAIL_LB, 'P-22/038': _EMAIL_AC, 'P-22/039': _EMAIL_AC, 'P-22/040': _EMAIL_LB,
    'P-22/041': _EMAIL_LB, 'P-22/042': _EMAIL_AC, 'P-22/043': _EMAIL_AC, 'P-22/044': _EMAIL_AC,
    'P-22/045': _EMAIL_AC, 'P-22/046': _EMAIL_AC, 'P-22/047': _EMAIL_SS, 'P-22/048': _EMAIL_LB,
    'P-22/049': _EMAIL_LB, 'P-22/050': _EMAIL_LB, 'P-22/051': _EMAIL_AC, 'P-22/052': _EMAIL_AC,
    'P-22/053': _EMAIL_SS, 'P-22/054': _EMAIL_SS, 'P-22/055': _EMAIL_AC, 'P-22/056': _EMAIL_AC,
    'P-22/057': _EMAIL_AC, 'P-22/058': _EMAIL_AC, 'P-22/059': _EMAIL_AC, 'P-22/060': _EMAIL_AC,
    'P-22/061': _EMAIL_LB, 'P-22/062': _EMAIL_SS, 'P-22/063': _EMAIL_SS, 'P-22/064': _EMAIL_LB,
    'P-22/065': _EMAIL_AC, 'P-22/066': _EMAIL_AC, 'P-22/067': _EMAIL_AC, 'P-22/068': _EMAIL_AC,
    'P-22/069': _EMAIL_AC, 'P-22/070': _EMAIL_SS, 'P-22/071': _EMAIL_AC, 'P-22/072': _EMAIL_LB,
    'P-22/073': _EMAIL_AC, 'P-22/074': _EMAIL_LB, 'P-22/075': _EMAIL_SS, 'P-22/076': _EMAIL_LB,
    'P-22/077': _EMAIL_AC, 'P-22/078': _EMAIL_AC, 'P-22/079': _EMAIL_AC, 'P-22/080': _EMAIL_SS,
    'P-22/081': _EMAIL_AC, 'P-22/082': _EMAIL_LB, 'P-22/083': _EMAIL_AC, 'P-22/084': _EMAIL_LB,
    'P-22/085': _EMAIL_LB, 'P-22/086': _EMAIL_LB, 'P-22/087': _EMAIL_LB, 'P-22/088': _EMAIL_LB,
    'P-22/089': _EMAIL_LB, 'P-22/090': _EMAIL_LB, 'P-22/091': _EMAIL_LB, 'P-22/092': _EMAIL_LB,
    'P-22/093': _EMAIL_LB, 'P-22/094': _EMAIL_LB, 'P-22/095': _EMAIL_LB, 'P-22/096': _EMAIL_LB,
    'P-22/097': _EMAIL_LB, 'P-22/098': _EMAIL_LB, 'P-22/099': _EMAIL_LB, 'P-22/100': _EMAIL_LB,
    'P-22/101': _EMAIL_LB, 'P-22/102': _EMAIL_LB, 'P-22/103': _EMAIL_LB, 'P-22/104': _EMAIL_LB,
    'P-22/105': _EMAIL_LB,
    'P-23/001': _EMAIL_LB, 'P-23/002': _EMAIL_LB, 'P-23/003': _EMAIL_LB, 'P-23/004': _EMAIL_AC,
    'P-23/005': _EMAIL_AC, 'P-23/006': _EMAIL_AC, 'P-23/007': _EMAIL_LB, 'P-23/008': _EMAIL_AC,
    'P-23/009': _EMAIL_AC, 'P-23/010': _EMAIL_AC, 'P-23/011': _EMAIL_SS, 'P-23/012': _EMAIL_AC,
    'P-23/013': _EMAIL_LB, 'P-23/014': _EMAIL_SS, 'P-23/015': _EMAIL_AC, 'P-23/016': _EMAIL_AC,
    'P-23/017': _EMAIL_SS, 'P-23/018': _EMAIL_AC, 'P-23/019': _EMAIL_LB, 'P-23/020': _EMAIL_AC,
    'P-23/021': _EMAIL_LB, 'P-23/022': _EMAIL_LB, 'P-23/023': _EMAIL_AC, 'P-23/024': _EMAIL_LB,
    'P-23/025': _EMAIL_LB, 'P-23/026': _EMAIL_SS, 'P-23/027': _EMAIL_LB, 'P-23/028': _EMAIL_LB,
    'P-23/029': _EMAIL_LB, 'P-23/030': _EMAIL_LB, 'P-23/031': _EMAIL_AC, 'P-23/032': _EMAIL_AC,
    'P-23/033': _EMAIL_AC, 'P-23/034': _EMAIL_SS, 'P-23/035': _EMAIL_AC, 'P-23/036': _EMAIL_AC,
    'P-23/037': _EMAIL_LB, 'P-23/038': _EMAIL_LB, 'P-23/039': _EMAIL_LB, 'P-23/040': _EMAIL_AC,
    'P-23/041': _EMAIL_AC, 'P-23/042': _EMAIL_LB, 'P-23/043': _EMAIL_LB, 'P-23/044': _EMAIL_LB,
    'P-23/045': _EMAIL_AC, 'P-23/046': _EMAIL_SS, 'P-23/047': _EMAIL_AC, 'P-23/048': _EMAIL_SS,
    'P-23/049': _EMAIL_LB, 'P-23/050': _EMAIL_LB, 'P-23/051': _EMAIL_AC, 'P-23/052': _EMAIL_AC,
    'P-23/053': _EMAIL_AC, 'P-23/054': _EMAIL_AC, 'P-23/055': _EMAIL_AC, 'P-23/056': _EMAIL_SS,
    'P-23/057': _EMAIL_LB, 'P-23/058': _EMAIL_AC, 'P-23/059': _EMAIL_LB, 'P-23/060': _EMAIL_AC,
    'P-23/061': _EMAIL_LB, 'P-23/062': _EMAIL_AC, 'P-23/063': _EMAIL_AC, 'P-23/064': _EMAIL_AC,
    'P-23/065': _EMAIL_AC, 'P-23/066': _EMAIL_AC, 'P-23/067': _EMAIL_AC, 'P-23/068': _EMAIL_AC,
    'P-23/069': _EMAIL_AC, 'P-23/070': _EMAIL_AC, 'P-23/071': _EMAIL_AC, 'P-23/072': _EMAIL_LB,
    'P-23/073': _EMAIL_AC, 'P-23/074': _EMAIL_SS, 'P-23/075': _EMAIL_LB, 'P-23/076': _EMAIL_LB,
    'P-23/077': _EMAIL_AC, 'P-23/078': _EMAIL_AC, 'P-23/079': _EMAIL_LB, 'P-23/080': _EMAIL_AC,
    'P-23/081': _EMAIL_AC, 'P-23/082': _EMAIL_AC, 'P-23/083': _EMAIL_AC, 'P-23/084': _EMAIL_AC,
    'P-23/085': _EMAIL_AC, 'P-23/086': _EMAIL_AC, 'P-23/087': _EMAIL_AC, 'P-23/088': _EMAIL_AC,
    'P-23/089': _EMAIL_SS, 'P-23/090': _EMAIL_AC, 'P-23/091': _EMAIL_AC, 'P-23/092': _EMAIL_LB,
    'P-23/093': _EMAIL_AC, 'P-23/094': _EMAIL_LB, 'P-23/095': _EMAIL_AC, 'P-23/096': _EMAIL_AC,
    'P-23/097': _EMAIL_AC, 'P-23/098': _EMAIL_LB, 'P-23/099': _EMAIL_LB, 'P-23/100': _EMAIL_AC,
    'P-23/101': _EMAIL_AC, 'P-23/102': _EMAIL_AC, 'P-23/103': _EMAIL_LB, 'P-23/104': _EMAIL_AC,
    'P-23/105': _EMAIL_SS,
    'P-24/001': _EMAIL_LB, 'P-24/002': _EMAIL_LB, 'P-24/003': _EMAIL_LB,
    'P-24/004': _EMAIL_AC, 'P-24/005': _EMAIL_AC, 'P-24/006': _EMAIL_AC, 'P-24/007': _EMAIL_AC,
    'P-24/008': _EMAIL_AC, 'P-24/009': _EMAIL_AC, 'P-24/010': _EMAIL_AC, 'P-24/011': _EMAIL_AC,
    'P-24/012': _EMAIL_SS, 'P-24/013': _EMAIL_AC, 'P-24/014': _EMAIL_AC, 'P-24/015': _EMAIL_SS,
    'P-24/016': _EMAIL_AC, 'P-24/017': _EMAIL_AC, 'P-24/018': _EMAIL_AC, 'P-24/019': _EMAIL_AC,
    'P-24/020': _EMAIL_AC, 'P-24/021': _EMAIL_AC, 'P-24/022': _EMAIL_AC, 'P-24/023': _EMAIL_AC,
    'P-24/024': _EMAIL_AC, 'P-24/025': _EMAIL_AC, 'P-24/026': _EMAIL_AC, 'P-24/027': _EMAIL_AC,
    'P-24/028': _EMAIL_AC, 'P-24/029': _EMAIL_AC, 'P-24/030': _EMAIL_AC, 'P-24/031': _EMAIL_AC,
    'P-24/032': _EMAIL_AC, 'P-24/033': _EMAIL_AC, 'P-24/034': _EMAIL_AC, 'P-24/035': _EMAIL_AC,
    'P-24/036': _EMAIL_AC, 'P-24/037': _EMAIL_AC, 'P-24/038': _EMAIL_AC, 'P-24/039': _EMAIL_AC,
    'P-24/040': _EMAIL_AC, 'P-24/041': _EMAIL_AC, 'P-24/042': _EMAIL_AC, 'P-24/043': _EMAIL_AC,
    'P-24/044': _EMAIL_AC, 'P-24/045': _EMAIL_AC, 'P-24/046': _EMAIL_AC, 'P-24/047': _EMAIL_AC,
    'P-24/048': _EMAIL_AC, 'P-24/049': _EMAIL_AC, 'P-24/050': _EMAIL_AC, 'P-24/051': _EMAIL_AC,
    'P-24/052': _EMAIL_AC, 'P-24/053': _EMAIL_AC, 'P-24/054': _EMAIL_AC, 'P-24/055': _EMAIL_AC,
    'P-24/056': _EMAIL_AC, 'P-24/057': _EMAIL_AC, 'P-24/058': _EMAIL_AC, 'P-24/059': _EMAIL_AC,
    'P-24/060': _EMAIL_AC, 'P-24/061': _EMAIL_AC, 'P-24/062': _EMAIL_AC, 'P-24/063': _EMAIL_AC,
    'P-24/064': _EMAIL_AC, 'P-24/065': _EMAIL_AC, 'P-24/066': _EMAIL_LB, 'P-24/067': _EMAIL_AC,
    'P-24/068': _EMAIL_AC, 'P-24/069': _EMAIL_LB, 'P-24/070': _EMAIL_LB, 'P-24/071': _EMAIL_AC,
    'P-24/072': _EMAIL_AC, 'P-24/073': _EMAIL_AC, 'P-24/074': _EMAIL_AC, 'P-24/075': _EMAIL_AC,
    'P-24/076': _EMAIL_AC, 'P-24/077': _EMAIL_AC, 'P-24/078': _EMAIL_AC, 'P-24/079': _EMAIL_SS,
    'P-24/080': _EMAIL_SS, 'P-24/081': _EMAIL_AC, 'P-24/082': _EMAIL_AC, 'P-24/083': _EMAIL_AC,
    'P-24/084': _EMAIL_AC, 'P-24/085': _EMAIL_LB, 'P-24/086': _EMAIL_CCH, 'P-24/087': _EMAIL_AC,
    'P-24/088': _EMAIL_AC, 'P-24/089': _EMAIL_AC, 'P-24/090': _EMAIL_AC, 'P-24/091': _EMAIL_AC,
    'P-24/092': _EMAIL_SS, 'P-24/093': _EMAIL_LB, 'P-24/094': _EMAIL_LB, 'P-24/095': _EMAIL_AC,
    'P-24/096': _EMAIL_CCH, 'P-24/097': _EMAIL_AC, 'P-24/098': _EMAIL_CCH, 'P-24/099': _EMAIL_CCH,
    'P-24/100': _EMAIL_SS,
    'P-25/001': _EMAIL_AC, 'P-25/002': _EMAIL_AC, 'P-25/003': _EMAIL_SS,
    'P-25/004': _EMAIL_AC, 'P-25/005': _EMAIL_SS, 'P-25/006': _EMAIL_CCH, 'P-25/007': _EMAIL_SS,
    'P-25/008': _EMAIL_AC, 'P-25/009': _EMAIL_AC, 'P-25/010': _EMAIL_AC, 'P-25/011': _EMAIL_AC,
    'P-25/012': _EMAIL_AC, 'P-25/013': _EMAIL_AC, 'P-25/014': _EMAIL_AC, 'P-25/015': _EMAIL_SS,
    'P-25/016': _EMAIL_AC, 'P-25/017': _EMAIL_AC, 'P-25/018': _EMAIL_AC, 'P-25/019': _EMAIL_CCH,
    'P-25/020': _EMAIL_AC, 'P-25/021': _EMAIL_AC, 'P-25/022': _EMAIL_AC, 'P-25/023': _EMAIL_SS,
    'P-25/024': _EMAIL_SS, 'P-25/025': _EMAIL_AC, 'P-25/026': _EMAIL_LB, 'P-25/027': _EMAIL_LB,
    'P-25/028': _EMAIL_LB, 'P-25/029': _EMAIL_AC, 'P-25/030': _EMAIL_SS, 'P-25/031': _EMAIL_SS,
    'P-25/032': _EMAIL_AC, 'P-25/033': _EMAIL_AC, 'P-25/034': _EMAIL_CCH, 'P-25/035': _EMAIL_CCH,
    'P-25/036': _EMAIL_LB, 'P-25/037': _EMAIL_AC, 'P-25/038': _EMAIL_AC, 'P-25/039': _EMAIL_AC,
    'P-25/040': _EMAIL_SS, 'P-25/041': _EMAIL_AC, 'P-25/042': _EMAIL_AC, 'P-25/043': _EMAIL_SS,
    'P-25/044': _EMAIL_SS, 'P-25/045': _EMAIL_LB, 'P-25/046': _EMAIL_LB, 'P-25/047': _EMAIL_AC,
    'P-25/048': _EMAIL_CCH, 'P-25/049': _EMAIL_CCH, 'P-25/050': _EMAIL_LB, 'P-25/051': _EMAIL_AC,
    'P-25/052': _EMAIL_SS, 'P-25/053': _EMAIL_AC, 'P-25/054': _EMAIL_LB, 'P-25/055': _EMAIL_AC,
    'P-25/056': _EMAIL_AC, 'P-25/057': _EMAIL_AC, 'P-25/058': _EMAIL_AC, 'P-25/059': _EMAIL_LB,
    'P-25/060': _EMAIL_AC, 'P-25/061': _EMAIL_AC, 'P-25/062': _EMAIL_AC, 'P-25/063': _EMAIL_LB,
    'P-25/064': _EMAIL_AC, 'P-25/065': _EMAIL_AC, 'P-25/066': _EMAIL_CCH, 'P-25/067': _EMAIL_AC,
    'P-25/068': _EMAIL_SS, 'P-25/069': _EMAIL_AC, 'P-25/070': _EMAIL_CCH, 'P-25/071': _EMAIL_AC,
    'P-25/072': _EMAIL_SS, 'P-25/073': _EMAIL_AC, 'P-25/074': _EMAIL_CCH, 'P-25/075': _EMAIL_AC,
    'P-25/076': _EMAIL_SS, 'P-25/077': _EMAIL_AC, 'P-25/078': _EMAIL_CCH, 'P-25/079': _EMAIL_AC,
    'P-25/080': _EMAIL_SS, 'P-25/081': _EMAIL_AC, 'P-25/082': _EMAIL_CCH, 'P-25/083': _EMAIL_AC,
    'P-25/084': _EMAIL_SS, 'P-25/085': _EMAIL_AC, 'P-25/086': _EMAIL_CCH, 'P-25/087': _EMAIL_AC,
    'P-25/088': _EMAIL_SS, 'P-25/089': _EMAIL_AC, 'P-25/090': _EMAIL_CCH, 'P-25/091': _EMAIL_AC,
    'P-25/092': _EMAIL_SS, 'P-25/093': _EMAIL_AC, 'P-25/094': _EMAIL_CCH, 'P-25/095': _EMAIL_AC,
    'P-25/096': _EMAIL_SS, 'P-25/097': _EMAIL_AC, 'P-25/098': _EMAIL_CCH, 'P-25/099': _EMAIL_AC,
    'P-26/001': _EMAIL_SS, 'P-26/002': _EMAIL_AC, 'P-26/003': _EMAIL_CCH, 'P-26/004': _EMAIL_AC,
    'P-26/005': _EMAIL_SS, 'P-26/006': _EMAIL_AC, 'P-26/007': _EMAIL_CCH, 'P-26/008': _EMAIL_AC,
    'P-26/009': _EMAIL_SS, 'P-26/010': _EMAIL_AC, 'P-26/011': _EMAIL_CCH, 'P-26/012': _EMAIL_AC,
    'P-26/013': _EMAIL_SS, 'P-26/014': _EMAIL_AC, 'P-26/015': _EMAIL_CCH, 'P-26/016': _EMAIL_AC,
    'P-26/017': _EMAIL_SS, 'P-26/018': _EMAIL_AC, 'P-26/019': _EMAIL_CCH, 'P-26/020': _EMAIL_AC,
    'P-26/021': _EMAIL_SS, 'P-26/022': _EMAIL_AC, 'P-26/023': _EMAIL_CCH, 'P-26/024': _EMAIL_AC,
    'P-26/025': _EMAIL_SS, 'P-26/026': _EMAIL_AC, 'P-26/027': _EMAIL_CCH, 'P-26/028': _EMAIL_AC,
    'P-26/029': _EMAIL_SS, 'P-26/030': _EMAIL_AC, 'P-26/031': _EMAIL_CCH, 'P-26/032': _EMAIL_AC,
    'P-26/033': _EMAIL_SS, 'P-26/034': _EMAIL_AC, 'P-26/035': _EMAIL_CCH, 'P-26/036': _EMAIL_AC,
}

# Email → iniciales para columna Responsable
EMAIL_TO_INITIALS = {
    'luis-bravo@eipsa.es': 'LB',
    'ana-calvo@eipsa.es': 'AC',
    'carlos-crespohor@eipsa.es': 'CCH',
    'jorge-valtierra@eipsa.es': 'JV',
}

# Doc type code → email CC responsable técnico
DOC_TYPE_EMAIL_MAP = {
    'CER': _EMAIL_JV, 'LIS': _EMAIL_JV, 'PRC': _EMAIL_JV,
    'MAN': _EMAIL_JV, 'CAT': _EMAIL_JV, 'DOS': _EMAIL_JV,
    'SPL': _EMAIL_JV, 'DD': _EMAIL_JV, 'SP': _EMAIL_JV,
}

# Destinatarios fijos
DEFAULT_TO = ["santos-sanchez@eipsa.es"]
DEFAULT_CC = ["jesus-martinez@eipsa.es", "ernesto-carrillo@eipsa.es"]


# ═══════════════════════════════════════════════════════
#  FUNCIONES COMPARTIDAS
# ═══════════════════════════════════════════════════════

def apply_po_mapping(df, po_col, mapping):
    df["Nº Pedido"] = df[po_col].astype(str).str.strip().map(mapping).fillna(df[po_col])
    return df


def apply_material_mapping(df, po_col, mapping):
    df["Material"] = df[po_col].astype(str).str.strip().map(mapping).fillna(df[po_col])
    return df


def apply_doc_type(df, code_col):
    df["Tipo de documento"] = df[code_col].map(DOC_TYPE_MAP)
    return df


def apply_critico(df):
    df["Crítico"] = df["Tipo de documento"].map(CRITICO_MAP).fillna("No")
    return df


def apply_fecha(df, received_time_str):
    df["Fecha"] = pd.to_datetime(received_time_str, dayfirst=True)
    return df


def fill_supp_nulls(df):
    if "Supp." in df.columns:
        df["Supp."] = df["Supp."].fillna("S00")
    else:
        df["Supp."] = "S00"
    return df


def identify_client(po: str) -> str:
    """Identifica cliente a partir de los primeros 5 caracteres del PO."""
    if not po or len(po) < 5:
        return ""
    return PO_CLIENT_MAP.get(po[:5], "")


def get_responsable_email(numero_pedido: str) -> str | None:
    """Devuelve email del responsable del proyecto por Nº Pedido."""
    for key, email in RESPONSABLE_PEDIDO_MAP.items():
        if key in str(numero_pedido):
            return email
    return None


def get_responsable_initials(numero_pedido: str) -> str:
    """Devuelve iniciales del responsable (LB, AC, etc.) por Nº Pedido."""
    email = get_responsable_email(numero_pedido)
    if email:
        return EMAIL_TO_INITIALS.get(email, "")
    return ""


def get_doc_type_cc(doc_type_code: str) -> str | None:
    """Devuelve email CC del responsable técnico por código de tipo doc."""
    if not doc_type_code:
        return None
    return DOC_TYPE_EMAIL_MAP.get(doc_type_code.upper(), None)


def compute_recipients(df) -> tuple[list[str], list[str]]:
    """Calcula To y CC dinámicos basándose en Nº Pedido y tipo doc."""
    to_set = set(DEFAULT_TO)
    cc_set = set(DEFAULT_CC)

    if len(df) > 0:
        first = df.iloc[0]
        n_pedido = str(first.get("Nº Pedido", ""))
        resp_email = get_responsable_email(n_pedido)
        if resp_email:
            to_set.add(resp_email)

        # Buscar CC por tipo de documento (invertir DOC_TYPE_MAP)
        tipo_to_codes = {}
        for code, nombre in DOC_TYPE_MAP.items():
            tipo_to_codes.setdefault(nombre, []).append(code)

        for _, row in df.iterrows():
            # Intentar con _doc_code primero, luego buscar por Tipo de documento
            doc_code = str(row.get("_doc_code", ""))
            if doc_code:
                cc_email = get_doc_type_cc(doc_code)
                if cc_email:
                    cc_set.add(cc_email)
                    continue
            tipo = str(row.get("Tipo de documento", ""))
            for code in tipo_to_codes.get(tipo, []):
                cc_email = get_doc_type_cc(code)
                if cc_email:
                    cc_set.add(cc_email)
                    break

    return sorted(to_set), sorted(cc_set)


def _load_logo_b64() -> str | None:
    """Intenta cargar el logo EIPSA con fondo transparente, como base64."""
    import base64, os, io
    try:
        from PIL import Image
    except ImportError:
        Image = None

    candidates = [
        r"M:\Comunes\JOSE\07 LOGOTIPOS\EIPSA NEW LOGO, CORTADO.png",
        os.path.join(os.path.dirname(__file__), "..", "..", "assets", "eipsa_logo.png"),
    ]
    TARGET_HEIGHT = 48  # px — tamaño final intrínseco

    for path in candidates:
        try:
            with open(path, "rb") as f:
                raw = f.read()

            if Image:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")

                # Eliminar fondo blanco/casi-blanco
                WHITE_THRESH = 230
                data = img.getdata()
                new_data = [
                    (255, 255, 255, 0) if r > WHITE_THRESH and g > WHITE_THRESH and b > WHITE_THRESH
                    else (r, g, b, a)
                    for r, g, b, a in data
                ]
                img.putdata(new_data)

                # Redimensionar
                ratio = TARGET_HEIGHT / img.height
                new_size = (int(img.width * ratio), TARGET_HEIGHT)
                img = img.resize(new_size, Image.LANCZOS)

                buf = io.BytesIO()
                img.save(buf, format="PNG")
                raw = buf.getvalue()

            return base64.b64encode(raw).decode()
        except Exception:
            continue
    return None


def build_notification_html(df_info_dict, df_docs, deadline_date):
    """Genera el HTML del email de notificación — diseño corporativo EIPSA."""
    from collections import Counter

    # ── Paleta EIPSA ──
    NAVY   = "#1B3A5C"   # azul corporativo EIPSA
    CYAN   = "#00AEEF"   # azul claro del logo
    NAVY_L = "#234B73"   # navy más claro para hover/stripe

    # Colores por estado
    STATUS_BG   = {"Rechazado": "#FFEBEE", "Com. Menores": "#FFF3E0", "Com. Mayores": "#FCE4EC",
                   "Aprobado": "#E8F5E9", "Comentado": "#F3E5F5", "Informativo": "#E3F2FD", "Eliminado": "#F5F5F5"}
    STATUS_TEXT = {"Rechazado": "#C62828", "Com. Menores": "#E65100", "Com. Mayores": "#AD1457",
                   "Aprobado": "#2E7D32", "Comentado": "#6A1B9A", "Informativo": "#1565C0", "Eliminado": "#757575"}
    STATUS_DOT  = {"Rechazado": "#E53935", "Com. Menores": "#FB8C00", "Com. Mayores": "#EC407A",
                   "Aprobado": "#43A047", "Comentado": "#AB47BC", "Informativo": "#1E88E5", "Eliminado": "#BDBDBD"}

    # ── Fecha límite ──
    deadline_str = deadline_date.strftime("%d de %B de %Y").replace(
        "January","enero").replace("February","febrero").replace("March","marzo").replace("April","abril").replace(
        "May","mayo").replace("June","junio").replace("July","julio").replace("August","agosto").replace(
        "September","septiembre").replace("October","octubre").replace("November","noviembre").replace("December","diciembre")

    # ── Logo ──
    logo_b64 = _load_logo_b64()
    if logo_b64:
        logo_html = (
            f'<img src="data:image/png;base64,{logo_b64}" '
            f'alt="DocFlow" style="display:block;height:24px;width:auto;" />'
        )
    else:
        logo_html = (
            f'<span style="font-size:18px;font-weight:900;color:#FFFFFF;letter-spacing:1px;">DocFlow</span>'
        )

    # ── Info del pedido: tarjetas en grid 3 columnas ──
    items = [(k, v) for k, v in df_info_dict.items() if v]
    info_rows_html = ""
    for i in range(0, len(items), 3):
        chunk = items[i:i+3]
        cells = ""
        for k, v in chunk:
            cells += (
                f'<td style="padding:0 6px 12px;width:33%;">'
                f'<table cellpadding="0" cellspacing="0" style="width:100%;background:#F8FAFF;'
                f'border:1px solid #DDE3F5;border-radius:6px;">'
                f'<tr><td style="padding:10px 14px;border-left:3px solid {CYAN};">'
                f'<p style="margin:0;font-size:10px;font-weight:700;color:{CYAN};text-transform:uppercase;'
                f'letter-spacing:0.06em;">{k}</p>'
                f'<p style="margin:3px 0 0;font-size:13px;font-weight:700;color:{NAVY};">{v}</p>'
                f'</td></tr></table></td>'
            )
        # Rellenar celdas vacías si el chunk es < 3
        for _ in range(3 - len(chunk)):
            cells += '<td style="padding:0 6px 12px;width:33%;"></td>'
        info_rows_html += f'<tr>{cells}</tr>'

    # ── Tabla de documentos ──
    cols = ["Doc. Cliente", "Título", "Rev.", "Estado"]
    available_cols = [c for c in cols if c in df_docs.columns]

    th_style = (f"background:{NAVY};color:#FFFFFF;padding:10px 14px;font-size:10px;font-weight:700;"
                f"letter-spacing:0.06em;text-transform:uppercase;text-align:left;")
    header_cells = "".join(f'<th style="{th_style}">{c}</th>' for c in available_cols)

    doc_rows = ""
    for i, (_, row) in enumerate(df_docs.iterrows()):
        estado = str(row.get("Estado", ""))
        bg_row = "#F8FAFF" if i % 2 == 0 else "#FFFFFF"
        cells = ""
        for c in available_cols:
            val = str(row.get(c, "") or "—")
            if c == "Estado":
                sbg  = STATUS_BG.get(estado, "#F5F5F5")
                stxt = STATUS_TEXT.get(estado, "#424242")
                sdot = STATUS_DOT.get(estado, "#BDBDBD")
                cells += (
                    f'<td style="padding:10px 14px;border-bottom:1px solid #EEF2F7;">'
                    f'<span style="display:inline-flex;align-items:center;gap:5px;padding:4px 10px;'
                    f'border-radius:20px;background:{sbg};color:{stxt};font-size:11px;font-weight:700;">'
                    f'<span style="width:6px;height:6px;border-radius:50%;background:{sdot};flex-shrink:0;"></span>'
                    f'{val}</span></td>'
                )
            elif c == "Rev.":
                cells += (
                    f'<td style="padding:10px 14px;border-bottom:1px solid #EEF2F7;text-align:center;">'
                    f'<span style="color:#E53935;font-size:12px;font-weight:700;">{val}</span></td>'
                )
            elif c == "Doc. Cliente":
                cells += (
                    f'<td style="padding:10px 14px;border-bottom:1px solid #EEF2F7;'
                    f'font-family:\'Courier New\',monospace;font-size:11px;color:#37474F;white-space:nowrap;">{val}</td>'
                )
            else:
                cells += (
                    f'<td style="padding:10px 14px;border-bottom:1px solid #EEF2F7;'
                    f'font-size:12px;color:#37474F;line-height:1.5;">{val}</td>'
                )
        doc_rows += f'<tr style="background:{bg_row};">{cells}</tr>'

    # ── Resumen de estados ──
    estado_counts = Counter(str(row.get("Estado", "")) for _, row in df_docs.iterrows())
    summary_badges = ""
    for estado, count in estado_counts.items():
        sbg  = STATUS_BG.get(estado, "#F5F5F5")
        stxt = STATUS_TEXT.get(estado, "#424242")
        sdot = STATUS_DOT.get(estado, "#BDBDBD")
        summary_badges += (
            f'<span style="display:inline-flex;align-items:center;gap:5px;padding:5px 12px;'
            f'border-radius:20px;background:{sbg};color:{stxt};font-size:12px;font-weight:700;margin-right:8px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{sdot};"></span>'
            f'{count} {estado}</span>'
        )

    n_docs = len(df_docs)
    doc_label = "Documento devuelto" if n_docs == 1 else "Documentos devueltos"

    # ── Preheader (preview text en Outlook) ──
    _pedido = df_info_dict.get("Nº Pedido", "") or ""
    _cliente = df_info_dict.get("Cliente", "") or ""
    _estado_principal = estado_counts.most_common(1)[0][0] if estado_counts else ""
    preheader_text = " · ".join(x for x in [_pedido, _cliente, f"{n_docs} doc(s)", _estado_principal] if x)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#EEF2F9;font-family:Arial,Helvetica,sans-serif;">

<!-- Preheader oculto: visible en la línea de preview de Outlook -->
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:#EEF2F9;">{preheader_text}</div>

<table width="100%" cellpadding="0" cellspacing="0" style="background:#EEF2F9;padding:32px 0;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(30,45,125,0.12);">

  <!-- ═══ HEADER ═══ -->
  <tr>
    <td style="background:{NAVY};padding:14px 28px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;">{logo_html}</td>
          <td style="vertical-align:middle;text-align:right;">
            <p style="margin:0;font-size:14px;font-weight:700;color:#FFFFFF;letter-spacing:0.02em;">
              Devolución de Documentación
            </p>
            <p style="margin:4px 0 0;font-size:11px;color:{CYAN};letter-spacing:0.04em;text-transform:uppercase;">
              Notificación Automática
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- ═══ CUERPO ═══ -->
  <tr>
    <td style="padding:20px 28px 0;">

      <!-- Info del pedido -->
      <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:{CYAN};text-transform:uppercase;letter-spacing:0.08em;">
        Datos del pedido
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;table-layout:fixed;">
        {info_rows_html}
      </table>

      <!-- Resumen estados -->
      <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:{CYAN};text-transform:uppercase;letter-spacing:0.08em;">
        Resumen
      </p>
      <div style="margin-bottom:24px;">{summary_badges}</div>

      <!-- Tabla documentos -->
      <p style="margin:0 0 10px;font-size:10px;font-weight:700;color:{CYAN};text-transform:uppercase;letter-spacing:0.08em;">
        {doc_label} ({n_docs})
      </p>
      <table cellpadding="0" cellspacing="0" style="width:100%;border-radius:8px;overflow:hidden;border:1px solid #DDE3F5;margin-bottom:28px;">
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{doc_rows}</tbody>
      </table>

      <!-- Aviso plazo -->
      <table cellpadding="0" cellspacing="0" style="width:100%;border-radius:8px;overflow:hidden;margin-bottom:28px;">
        <tr>
          <td style="background:#FFF8E1;border:1px solid #FFE082;border-radius:8px;padding:14px 18px;">
            <table cellpadding="0" cellspacing="0" width="100%">
              <tr>
                <td style="vertical-align:top;width:28px;font-size:18px;padding-top:1px;">&#9888;</td>
                <td>
                  <p style="margin:0;font-size:13px;font-weight:700;color:#BF6C00;">
                    Plazo de respuesta:
                    <span style="color:#C62828;">{deadline_str}</span>
                  </p>
                  <p style="margin:4px 0 0;font-size:12px;color:#795548;">
                    La documentación debe ser revisada, actualizada en ERP y subida antes de esta fecha.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

    </td>
  </tr>

  <!-- ═══ FOOTER ═══ -->
  <tr>
    <td style="background:#F4F7FC;border-top:3px solid {CYAN};padding:18px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="margin:0;font-size:12px;font-weight:700;color:{NAVY};">
              Document Control
            </p>
            <p style="margin:3px 0 0;font-size:11px;color:#90A4AE;">
              DocFlow &nbsp;·&nbsp; © 2026 <a href="https://jparedesds.github.io/" style="color:#90A4AE;text-decoration:underline;">jparedesDS</a> &nbsp;·&nbsp; Todos los derechos reservados
            </p>
          </td>
          <td style="text-align:right;vertical-align:middle;">
            <p style="margin:0;font-size:10px;color:#B0BEC5;">
              {datetime.now().strftime("%d/%m/%Y")}
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

</table>
</td></tr>
</table>

</body>
</html>"""
    return html


def lookup_erp(numero_pedido: str) -> dict:
    """Busca en data_erp.xlsx por Nº Pedido y devuelve Cliente, Material, etc."""
    import os
    from utils.config import DATA_ERP_PATH

    if not numero_pedido or not os.path.exists(DATA_ERP_PATH):
        return {}
    try:
        df = pd.read_excel(DATA_ERP_PATH, engine="openpyxl")
    except Exception:
        return {}

    mask = df["Nº Pedido"].astype(str).str.strip().str.contains(
        re.escape(numero_pedido), case=False, na=False
    )
    if mask.any():
        row = df[mask].iloc[0]
        return {k: str(row[k]) if pd.notna(row.get(k)) else ""
                for k in ("Cliente", "Material", "Nº PO")}
    return {}


def lookup_erp_by_npo(npo: str) -> dict:
    """Busca en data_erp.xlsx por Nº PO y devuelve Nº Pedido, Cliente, Material."""
    import os
    from utils.config import DATA_ERP_PATH

    if not npo or not os.path.exists(DATA_ERP_PATH):
        return {}
    try:
        df = pd.read_excel(DATA_ERP_PATH, engine="openpyxl")
    except Exception:
        return {}

    if "Nº PO" not in df.columns:
        return {}

    mask = df["Nº PO"].astype(str).str.strip().str.contains(
        re.escape(npo), case=False, na=False
    )
    if mask.any():
        row = df[mask].iloc[0]
        return {k: str(row[k]) if pd.notna(row.get(k)) else ""
                for k in ("Nº Pedido", "Cliente", "Material")}
    return {}


FINAL_COLUMNS = [
    "Nº Pedido", "Supp.", "Responsable", "Cliente", "Material", "PO",
    "Doc. EIPSA", "Doc. Cliente", "Título", "Rev.", "Estado",
    "Tipo de documento", "Crítico", "Nº Transmittal", "Fecha",
]
