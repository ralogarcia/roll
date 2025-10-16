# ads_iframe_anchor_patrocinado.py
# Extrae título/desc anclando en etiquetas tipo “Patrocinado” (variantes ES/EN) dentro del iframe correcto.
# Ahora con POLLING: corta la espera en cuanto aparece el anchor (si no, hace fallback estable).
#
# Requisitos:
#   pip install selenium webdriver-manager pandas

import re
import time
import random
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ================= Config =================
DATA_DIR    = Path("Data Google")
INPUT_CSV   = DATA_DIR / "ads_master_20250901_20250925.csv"
OUTPUT_CSV  = DATA_DIR / "ads_master_20250901_20250925_with_text.csv"

OUT_DIR     = DATA_DIR / "iframe_anchor_pat"
DIR_SCR     = OUT_DIR / "screens"   # se crea solo si SAVE_SCREENSHOT=True
DIR_TXT     = OUT_DIR / "text"
LOG_FILE    = OUT_DIR / "iframe_anchor_pat.log"
CHROMEDRIVER_LOG = OUT_DIR / "chromedriver.log"

COL_LINK    = "details_link"

# Espera por polling del anchor (máximo) y frecuencia de chequeo
ANCHOR_TIMEOUT = 15.0
POLL_INTERVAL  = 0.5

BETWEEN_URL = (1.0, 2.0)  # pausa entre URLs
SAVE_EVERY  = 10          # guarda el CSV cada N filas
SAVE_SCREENSHOT = False   # desactiva screenshots

# Filtros de líneas y ruido
MIN_LEN, MAX_LEN = 6, 220
URL_RE = re.compile(r"(https?://|www\.)", re.I)
NOISE_PREFIXES = tuple(s.lower() for s in (
    "aplicaciones de google", "menú principal", "imagen de", "ir al contenido",
    "go to ads transparency center home page", "go to", "visita", "más información",
    "política de privacidad", "términos", "configuración"
))

# Caracteres de control/bidi (incluye '⁦' '⁩')
BIDI_CHARS = "".join(chr(c) for c in (
    0x200E, 0x200F,              # LRM, RLM
    0x202A, 0x202B, 0x202D, 0x202E, 0x202C,  # LRE/RLE/LRO/RLO/PDF
    0x2066, 0x2067, 0x2068, 0x2069           # LRI/RLI/FSI/PDI
))
BIDI_RX = re.compile(f"[{re.escape(BIDI_CHARS)}]")

# Variantes de la etiqueta tipo "Patrocinado" (cortas y seguras)
ANCHOR_PATTERNS = [
    r"\bpatrocinad[oa]\b",          # Patrocinado / Patrocinada
    r"\bpatrocinado\s+por\b",       # Patrocinado por
    r"\bpromocionad[oa]\b",         # Promocionado / Promocionada
    r"\bpromocionado\s+por\b",      # Promocionado por
    r"\bpublicidad\b",              # Publicidad
    r"\banuncio\b",                 # Anuncio
    r"\bsponsored\b",               # Sponsored
    r"\bsponsored\s+by\b",          # Sponsored by
    r"^\s*ad\s*$",                  # "Ad" como línea sola
    r"\badvertisement\b",           # Advertisement
]
ANCHOR_RX = [re.compile(pat, re.IGNORECASE) for pat in ANCHOR_PATTERNS]
# ==========================================

# ---------- Logger limpio ----------
logger = logging.getLogger("adscrape")

def setup_logging():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if SAVE_SCREENSHOT:
        DIR_SCR.mkdir(parents=True, exist_ok=True)
    DIR_TXT.mkdir(parents=True, exist_ok=True)

    # Silenciar terceros ruidosos
    logging.getLogger().setLevel(logging.WARNING)
    for noisy in ("WDM", "seleniumwire", "urllib3", "selenium"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Nuestro logger: consola (INFO) + archivo (INFO)
    logger.setLevel(logging.INFO)
    fmt_console = logging.Formatter("%(asctime)s | %(levelname).1s | %(message)s", "%H:%M:%S")
    fmt_file    = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt_console)
    ch.setLevel(logging.INFO)

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt_file)
    fh.setLevel(logging.INFO)

    if not logger.handlers:
        logger.addHandler(ch)
        logger.addHandler(fh)

    logger.info("======== Inicio: IFRAME anclado por etiqueta de patrocinio (polling) ========")
    logger.info(f"Input: {INPUT_CSV.name}  → Output: {OUTPUT_CSV.name}")

def shorten(s: str, n: int = 90) -> str:
    s = (s or "").strip()
    return (s[: n-1] + "…") if len(s) > n else s

def build_driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")   # visible
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--lang=es-ES,es;q=0.9,en;q=0.8")

    try:
        service = Service(ChromeDriverManager().install(), log_output=str(CHROMEDRIVER_LOG))
    except TypeError:
        # Selenium viejo sin 'log_output'
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=opts)
    logger.info("Chrome listo.")
    return driver

# ---------- Utilidades de parsing ----------
def clean_line(s: str) -> str:
    if not s:
        return ""
    s = BIDI_RX.sub("", s)            # quita aislates/bi-di
    s = s.replace("\xa0", " ")        # NBSP → espacio normal
    return s.strip()

def good_line(s: str) -> bool:
    if not s: return False
    s = clean_line(s)
    if len(s) < MIN_LEN or len(s) > MAX_LEN: return False
    if URL_RE.search(s): return False
    if sum(ch.isalpha() for ch in s) < 3: return False
    if s.lower() in NOISE_PREFIXES: return False
    return True

def lines_from_text(txt: str) -> List[str]:
    raw = (txt or "").splitlines()
    return [clean_line(ln) for ln in raw if clean_line(ln)]

def find_anchor_index(lines: List[str]) -> Tuple[Optional[int], Optional[str]]:
    """Devuelve (idx, patrón_coincidente) de la primera línea que matchea alguna variante."""
    for i, ln in enumerate(lines):
        text = ln.lower()
        for rx in ANCHOR_RX:
            if rx.search(text):
                return i, rx.pattern
    return None, None

def extract_after_anchor(lines: List[str], anchor_idx: int) -> Tuple[str, str, str]:
    """
    Título = 1a línea 'buena' después del anchor.
    Descripción = 1–2 líneas 'buenas' siguientes.
    Snippet = anchor + hasta 3 líneas siguientes.
    """
    title = ""
    desc_parts: List[str] = []
    j = anchor_idx + 1

    while j < len(lines):
        ln = lines[j]
        if good_line(ln):
            title = ln
            j += 1
            break
        j += 1

    while j < len(lines) and len(desc_parts) < 2:
        ln = lines[j]
        if good_line(ln):
            desc_parts.append(ln)
        j += 1

    if not title and not desc_parts:
        return "", "", ""

    desc = " ".join(desc_parts).strip()
    tail = lines[anchor_idx: min(len(lines), anchor_idx + 4)]
    snippet = " | ".join(tail)
    return title, desc, snippet

# ---------- Detección temprana del anchor (polling) ----------
def detect_anchor_context(driver) -> Optional[Dict]:
    """
    Busca el anchor en iframes y en el documento.
    Devuelve un dict de contexto si lo encuentra:
      {'kind': 'iframe'|'document', 'index': <int or None>, 'inner': <str>, 'anchor_idx': <int>}
    """
    # 1) iframes
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for k in range(len(frames)):
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            frame = frames[k]
            try:
                driver.switch_to.frame(frame)
            except Exception:
                continue
            inner = driver.execute_script("return document.body && document.body.innerText || ''") or ""
            lines = lines_from_text(inner)
            anchor_idx, _ = find_anchor_index(lines)
            driver.switch_to.default_content()
            if anchor_idx is not None:
                return {"kind": "iframe", "index": k, "inner": inner, "anchor_idx": anchor_idx}
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    # 2) documento
    try:
        inner = driver.execute_script("return document.body && document.body.innerText || ''") or ""
        lines = lines_from_text(inner)
        anchor_idx, _ = find_anchor_index(lines)
        if anchor_idx is not None:
            return {"kind": "document", "index": None, "inner": inner, "anchor_idx": anchor_idx}
    except Exception:
        pass

    return None

def wait_until_anchor_or_timeout(driver, timeout=ANCHOR_TIMEOUT, poll=POLL_INTERVAL) -> Tuple[bool, Optional[Dict]]:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        ctx = detect_anchor_context(driver)
        if ctx:
            return True, ctx
        time.sleep(poll)
    return False, None

def extract_from_cached_context(ctx: Dict, row_idx: int) -> Tuple[str, str, str, str, str, str]:
    """
    Usa el innerText ya detectado durante el polling para extraer y guardar artefactos.
    Devuelve (title, desc, where, source_detail, artifact_path, snippet).
    """
    lines = lines_from_text(ctx["inner"])
    t, d, snip = extract_after_anchor(lines, ctx["anchor_idx"])
    if ctx["kind"] == "iframe":
        k = ctx["index"]
        p = DIR_TXT / f"row{row_idx:04d}_iframe{k}_innerText.txt"
        p.write_text(ctx["inner"], encoding="utf-8")
        return t, d, "iframe_anchor_patrocinado", f"iframe_index={k}", str(p), snip
    else:
        p = DIR_TXT / f"row{row_idx:04d}_document_innerText.txt"
        p.write_text(ctx["inner"], encoding="utf-8")
        return t, d, "inner_anchor_patrocinado", "document.body.innerText", str(p), snip

# ---------- Extracción estable (por si no hubo detección temprana) ----------
def read_iframes_anchor(driver, row_idx: int):
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    best = None  # (title, desc, where, source_detail, artifact_path, snippet, idx)
    for k in range(len(frames)):
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            frame = frames[k]
            try:
                driver.switch_to.frame(frame)
            except Exception:
                continue

            inner = driver.execute_script("return document.body && document.body.innerText || ''") or ""
            p = DIR_TXT / f"row{row_idx:04d}_iframe{k}_innerText.txt"
            p.write_text(inner, encoding="utf-8")

            lines = lines_from_text(inner)
            anchor_idx, _ = find_anchor_index(lines)
            if anchor_idx is not None:
                t, d, snip = extract_after_anchor(lines, anchor_idx)
                if t or d:
                    if not best or (len(d) > len(best[1])):
                        best = (t, d, "iframe_anchor_patrocinado", f"iframe_index={k}", str(p), snip, k)

            driver.switch_to.default_content()
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    if best:
        t, d, w, s, path, snip, _ = best
        return t, d, w, s, path, snip
    return "", "", "", "", "", ""

def read_document_anchor(driver, row_idx: int):
    try:
        inner = driver.execute_script("return document.body && document.body.innerText || ''") or ""
        p = DIR_TXT / f"row{row_idx:04d}_document_innerText.txt"
        p.write_text(inner, encoding="utf-8")
        lines = lines_from_text(inner)
        anchor_idx, _ = find_anchor_index(lines)
        if anchor_idx is not None:
            t, d, snip = extract_after_anchor(lines, anchor_idx)
            if t or d:
                return t, d, "inner_anchor_patrocinado", "document.body.innerText", str(p), snip

        # Fallback mínimo: primeras líneas “buenas”
        cand = [ln for ln in lines if good_line(ln)]
        if cand:
            t = cand[0]
            d = " ".join(cand[1:3]).strip()
            snip = " | ".join(cand[:4])
            return t, d, "inner_text", "document.body.innerText", str(p), snip

        return "", "", "", "", "", ""
    except Exception:
        return "", "", "", "", "", ""

# ---------- Navegación ----------
def scrape_one(driver, url: str, row_idx: int):
    t0 = time.perf_counter()
    driver.get(url)

    # Polling: corta apenas aparece el anchor (máximo ANCHOR_TIMEOUT)
    found, ctx = wait_until_anchor_or_timeout(driver, ANCHOR_TIMEOUT, POLL_INTERVAL)

    if found and ctx:
        t, d, w, s, path, snip = extract_from_cached_context(ctx, row_idx)
    else:
        # Fallback estable (misma lógica de antes)
        t, d, w, s, path, snip = read_iframes_anchor(driver, row_idx)
        if not (t or d):
            t, d, w, s, path, snip = read_document_anchor(driver, row_idx)

    # Screenshot opcional (apagado por defecto)
    if SAVE_SCREENSHOT and (t or d):
        try:
            png = DIR_SCR / f"row{row_idx:04d}.png"
            driver.save_screenshot(str(png))
        except Exception:
            pass

    dur = time.perf_counter() - t0
    return t, d, w, s, path, snip, dur

# ---------- Main ----------
def main():
    setup_logging()

    if not INPUT_CSV.exists():
        logger.error(f"No existe {INPUT_CSV}")
        return
    df = pd.read_csv(INPUT_CSV)
    if COL_LINK not in df.columns:
        logger.error(f"Falta columna '{COL_LINK}' en el CSV")
        return

    # Asegura columnas de salida
    for col in ("ad_title", "ad_text", "where", "source_detail", "artifact_path", "snippet"):
        if col not in df.columns:
            df[col] = ""

    driver = build_driver()

    # métricas
    stats = {"total": 0, "ok_iframe": 0, "ok_inner": 0, "fb_inner": 0, "empty": 0}

    try:
        for i, row in df.iterrows():
            url = str(row[COL_LINK]).strip()
            if not url:
                continue

            t, d, w, s, path, snip, dur = scrape_one(driver, url, i+1)

            df.at[i, "ad_title"] = t
            df.at[i, "ad_text"]  = d
            df.at[i, "where"]    = w
            df.at[i, "source_detail"] = s
            df.at[i, "artifact_path"] = path
            df.at[i, "snippet"]  = snip

            stats["total"] += 1
            if w.startswith("iframe_anchor"):
                stats["ok_iframe"] += 1; status = "OK"
            elif w == "inner_anchor_patrocinado":
                stats["ok_inner"] += 1; status = "OK*"
            elif w == "inner_text":
                stats["fb_inner"] += 1; status = "FB"
            else:
                stats["empty"] += 1; status = "—"

            logger.info(
                f"#{i+1:04d} | {status:<2} | {w or 'n/a'}"
                f"{(' | ' + s) if s else ''} | {dur:.1f}s | "
                f"T:'{shorten(t)}' | D:'{shorten(d)}'"
            )

            if (i + 1) % SAVE_EVERY == 0:
                df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
                logger.info(f"[auto-save] {OUTPUT_CSV.name} hasta fila {i+1}")

            time.sleep(random.uniform(*BETWEEN_URL))
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    logger.info(
        "======== Fin ========\n"
        f"Total procesados: {stats['total']}\n"
        f"OK por iframe:    {stats['ok_iframe']}\n"
        f"OK por inner:     {stats['ok_inner']}\n"
        f"Fallback inner:   {stats['fb_inner']}\n"
        f"Vacíos/errores:   {stats['empty']}\n"
        f"CSV: {OUTPUT_CSV}"
    )

if __name__ == "__main__":
    main()
