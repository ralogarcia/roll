import json
import csv
import re
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime, timezone
from serpapi import GoogleSearch

# ----------------- Configuración -----------------
start_date = "20250901"   # YYYYMMDD
end_date   = "20250925"

REGION  = "2484"          # México
API_KEY = "565cbe5bf274e5953d5a8b809004feb7f4859549b4d91364f182b90470a5671d"

# Listas de búsqueda
ADVERTISER_IDS = [
    "AR06522001263104622593",
"AR16223682401597915137",
"AR05897760305303257089",
"AR11972578885037457409",
"AR02912755010926280705",
"AR12622913693307371521",
"AR04411659152250634241",
"AR04411659152250634241",
"AR04411659152250634241",
"AR02912755010926280705",
"AR04411659152250634241"
]
DOMAINS = [
    "toyota.mx",
"toyotauniversidad.mx",
"volkswageninterlomas.com.mx",
"honda.mx",
"hondapedregal.mx",
"hondauniversidad.mx",
"hondametepec.mx",
"nissantollocan.com.mx",
"nissancountry.mx",
"nissancentral.com.mx",
"kiaaeropuerto.com.mx",
"kiamonterrey.mx",
"kiaixtapaluca.com",
"kiaaeropuerto.com.mx",
"kiazacatecas.com",
"kiacleber.com",
"mazda.mx",
"fiat.com.mx",
"fiatsantafe.com",
"distribuidoresfiatchrysler.com.mx",
"mgmotor.com.mx",
"mgmonclova.com",
"ford.mx",
"fordmylsa.mx",
"fordmylsaqueretaro.mx",
"fordmylsasanjuandelrio.mx",
"fordlomas.mx",
"hyundai.com.mx",
"hyundaidistribuidor.com.mx",
"chirey.mx",
"chireyboca.mx",
"chireydorada.mx",
"chireycancun.mx",
"chireycleber.com",
"chireymerida.mx",
"renaultuniversidad.com",
"jac.mx",
"jacsureste.mx",
"baicmexico.com",
"jmcmexico.com",
"jmcarcancun.mx",
"changan.mx",
"changanqro.com",
"changanleon.com",
"changanzamora.mx",
"changancelaya.mx",
"changanuruapan.mx",
"byd.com",
"bydtlalnepantla.com.mx",
"bydinterlomas.com.mx",
"bydpolanco.com.mx",
"bydacapulco.mx",
"bydaeropuerto.mx",
"bydsinaloa.com.mx",
"bydlomasverdes.com.mx",
"chevrolet.com.mx",
"chevrolettepic.com",
"chevroletangelopolis.com",
"chevroletdelparque.com.mx",
"chevroletjuriquilla.com.mx",
"mazda.mx",
"mazdadelaval.com",
"distribuidorestoyota.com.mx",
"distribuidoresfiatchrysler.com",
"hyundaidistribuidor.com.mx"
]

# Carpeta de salida
out_dir = Path("./Data Google")
out_dir.mkdir(parents=True, exist_ok=True)

MASTER_CSV  = out_dir / f"ads_master_{start_date}_{end_date}.csv"
SUMMARY_LOG = out_dir / f"ads_summary_{start_date}_{end_date}.log"

# Depuración
SAVE_JSON_DEBUG = True     # <<<<< ACTIVADO
MAX_PAGES = 50             # límite de seguridad

# ----------------- Utilidades -----------------
def epoch_to_iso(ts):
    if ts in (None, "", 0):
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

def pick(d: dict, key: str, default=""):
    v = d.get(key, default)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v

def ensure_master_csv(fieldnames):
    if not MASTER_CSV.exists():
        with open(MASTER_CSV, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

def append_rows(rows, fieldnames):
    with open(MASTER_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        for r in rows:
            writer.writerow(r)

def save_json_debug_page(results: dict, basename: str, page: int):
    if not SAVE_JSON_DEBUG:
        return
    json_path = out_dir / f"{basename}__p{page:03d}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"🧪 JSON página {page} guardado: {json_path.resolve()}")

def extract_ads_list(results: dict):
    ads = results.get("ad_creatives")
    if not ads:
        ads = results.get("ads_results") or results.get("results") or []
    return ads if isinstance(ads, list) else []

# ----------------- Extractor robusto de next_page_token -----------------
def extract_next_page_token(results: dict):
    """
    Busca token de paginación en rutas comunes:
    - results["next_page_token"]
    - results["pagination"]["next_page_token"]
    - results["serpapi_pagination"]["next_page_token"]
    - ... o lo extrae de un next_link con query param next_page_token=...
    """
    if not isinstance(results, dict):
        return None

    token = results.get("next_page_token")
    if token:
        return token

    for key in ("pagination", "serpapi_pagination"):
        obj = results.get(key)
        if isinstance(obj, dict):
            token = obj.get("next_page_token")
            if token:
                return token
            for link_key in ("next_link", "next", "next_page_url"):
                link = obj.get(link_key)
                if isinstance(link, str) and "next_page_token=" in link:
                    qs = parse_qs(urlparse(link).query)
                    cand = qs.get("next_page_token", [None])[0]
                    if cand:
                        return cand

    try:
        blob = json.dumps(results, ensure_ascii=False)
        m = re.search(r"next_page_token=([A-Za-z0-9_\-]+)", blob)
        if m:
            return m.group(1)
    except Exception:
        pass

    return None

# ----------------- Paginación (mejorada) -----------------
def fetch_all_ads_with_pagination(base_params: dict, basename: str):
    """
    Trae todas las páginas usando next_page_token sin modificar fechas.
    p1: base_params
    p>1: (1) {api_key, engine, next_page_token}
         (2) si no avanza, reintenta con region/fechas + criterio original.
    """
    all_ads = []
    page = 1
    params = dict(base_params)
    prev_token = None

    while True:
        print(f"   📥 Página {page} ...")
        results = GoogleSearch(params).get_dict() or {}

        if page == 1:
            print("   🔍 Claves JSON p1:", list(results.keys())[:12])

        save_json_debug_page(results, basename, page)

        ads = extract_ads_list(results)
        print(f"   🧮 Anuncios en esta página: {len(ads)}")
        if ads:
            all_ads.extend(ads)

        next_token = extract_next_page_token(results)
        if not next_token:
            print("   ⛳ Sin next_page_token: fin de paginación.")
            break

        if prev_token is not None and next_token == prev_token:
            print("   ⚠️ next_page_token repetido; se detiene para evitar loop.")
            break
        prev_token = next_token

        if page >= MAX_PAGES:
            print(f"   ⛔ Alcanzado MAX_PAGES={MAX_PAGES}, se detiene.")
            break

        # 1) Solo token
        tentative = {
            "api_key": base_params["api_key"],
            "engine": base_params["engine"],
            "next_page_token": next_token,
        }
        probe = GoogleSearch(tentative).get_dict() or {}
        probe_ads = extract_ads_list(probe)

        if probe_ads:
            save_json_debug_page(probe, basename, page + 1)
            params = tentative
        else:
            # 2) Reintento con parámetros completos + token
            params = {
                "api_key": base_params["api_key"],
                "engine": base_params["engine"],
                "region": base_params.get("region"),
                "start_date": base_params.get("start_date"),
                "end_date": base_params.get("end_date"),
                "num": base_params.get("num", 100),
                "next_page_token": next_token,
            }
            if "advertiser_id" in base_params:
                params["advertiser_id"] = base_params["advertiser_id"]
            if "text" in base_params:
                params["text"] = base_params["text"]

        page += 1

    return all_ads

# ----------------- CSV consolidado -----------------
FIELDNAMES = [
    "source_type", "query_value",
    "advertiser", "ad_creative_id", "format",
    "target_domain", "image", "width", "height",
    "total_days_shown",
    "first_shown_epoch", "first_shown_iso",
    "last_shown_epoch", "last_shown_iso",
    "details_link", "link",
]
ensure_master_csv(FIELDNAMES)

summary = []  # (source_type, value, count, note)

def run_query(source_type: str, value: str):
    base_params = {
        "api_key": API_KEY,
        "engine": "google_ads_transparency_center",
        "region": REGION,
        "start_date": start_date,
        "end_date": end_date,
        "num": 100,
    }
    if source_type == "advertiser_id":
        base_params["advertiser_id"] = value
        basename = f"advertiser_id__{value}_{start_date}_{end_date}"
    else:
        base_params["text"] = value
        basename = f"domain__{value}_{start_date}_{end_date}"

    print(f"🔎 Buscando ({source_type}): {value}")
    ads = fetch_all_ads_with_pagination(base_params, basename)

    rows = []
    for ad in ads:
        first_epoch = ad.get("first_shown")
        last_epoch  = ad.get("last_shown")
        rows.append({
            "source_type":       source_type,
            "query_value":       value,
            "advertiser":        pick(ad, "advertiser"),
            "ad_creative_id":    pick(ad, "ad_creative_id"),
            "format":            pick(ad, "format"),
            "target_domain":     pick(ad, "target_domain"),
            "image":             pick(ad, "image"),
            "width":             pick(ad, "width"),
            "height":            pick(ad, "height"),
            "total_days_shown":  pick(ad, "total_days_shown"),
            "first_shown_epoch": first_epoch if first_epoch else "",
            "first_shown_iso":   epoch_to_iso(first_epoch),
            "last_shown_epoch":  last_epoch if last_epoch else "",
            "last_shown_iso":    epoch_to_iso(last_epoch),
            "details_link":      pick(ad, "details_link"),
            "link":              pick(ad, "link"),
        })

    if rows:
        append_rows(rows, FIELDNAMES)
        print(f"✅ {len(rows)} anuncios agregados al maestro.")
        summary.append((source_type, value, len(rows), "OK"))
    else:
        print("ℹ️ Sin anuncios en esta búsqueda.")
        summary.append((source_type, value, 0, "NO_RESULTS"))

# ----------------- Ejecutar todas las búsquedas -----------------
for adv in ADVERTISER_IDS:
    run_query("advertiser_id", adv)

for dom in DOMAINS:
    run_query("domain", dom)

# ----------------- Resumen -----------------
total_rows = sum(c for _, _, c, _ in summary)
lines = []
lines.append(f"Resumen de ejecuciones ({start_date} a {end_date})")
lines.append(f"Total búsquedas: {len(summary)}")
lines.append(f"Total anuncios agregados: {total_rows}\n")
lines.append("Detalle por búsqueda:")
for src, val, cnt, note in summary:
    lines.append(f"- [{src}] {val} -> {cnt} anuncios ({note})")

no_hits = [(s, v) for s, v, c, _ in summary if c == 0]
if no_hits:
    lines.append("\nSin resultados:")
    for s, v in no_hits:
        lines.append(f"- [{s}] {v}")

with open(SUMMARY_LOG, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print("\n📁 Salidas:")
print(f"- CSV maestro: {MASTER_CSV.resolve()}")
print(f"- LOG resumen: {SUMMARY_LOG.resolve()}")
print("🔎 JSONs por búsqueda guardados en:", out_dir.resolve())
