# meta_ads_cards_by_id_with_text_clean_v2_id_xlsx_monthly.py
# Requisitos:
#   pip install -U selenium pandas openpyxl

import os, time, re
from urllib.parse import quote
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from subprocess import CREATE_NO_WINDOW

# -------------------- INICIO --------------------
START_TS = time.perf_counter()
print(f"[START] {datetime.now():%Y-%m-%d %H:%M:%S}")

QUERIES = [
    "honda mexico","honda méxico","honda",
"toyota mexico","toyota méxico","toyota",
"Nissan Mexico","Nissan México","Nissan",
"General Motors Mexico","General Motors México","General Motors",
"Chevrolet","Chevrolet Mexico",
"Volkswagen Mexico","Volkswagen México","Volkswagen",
"Kia Mexico","Kia México","Kia",
"Mazda Mexico","Mazda México","Mazda",
"Fiat Mexico","Fiat México","Fiat",
"MG Mexico","MG México","MG",
"Ford Mexico","Ford México","Ford",
"Hyundai Mexico","Hyundai México","Hyundai",
"Honda Mexico","Honda México","Honda",
"Chirey Mexico","Chirey México","Chirey",
"Renault Mexico","Renault México","Renault",
"JAC Mexico","JAC México","JAC",
"Mitsubishi Mexico","Mitsubishi México","Mitsubishi",
"BAIC Mexico","BAIC México","BAIC",
"JMC Mexico","JMC México","JMC",
"Changan Mexico","Changan México","Changan",
"BYD Mexico","BYD México","BYD",
"Asociación Nacional de Distribuidores de Automóviles Nissan, A.C. (ANDANAC)",
"Asociación Mexicana de Distribuidores General Motors, A.C. (AMDGM)",
"Asociación Mexicana de Distribuidores Ford, A.C. (AMDF)",
"Distribuidores Hyundai México, A.C. (DHM)",
"Asociación Mexicana de Franquiciatarios de Automotores Renault (AMEFAR)",
"Asociación Nacional de Concesionarios de Grupo Volkswagen, A.C. (ANCGVW)",
"Asociación Mexicana de Distribuidores Kia, A.C. (AMDK) | dealers Kia",
"Asociación mexicana de distribuidores fiat | Distribuidores Fiat",
"Asociación Mexicana de Concesionarios Honda, A.C. (AMECAH)",
"Asociación Mexicana de Distribuidores Mitsubishi, A.C."
]

# ====== CONTROLES RÁPIDOS ======
MAX_SCROLLS         = 25
INNER_WAIT_MAX      = 10.0
INNER_POLL_INTERVAL = 0.6
STALL_ROUNDS        = 3

# ====== CONFIG: Carpeta y nombre mensual ======
OUTPUT_DIR = os.path.join(os.getcwd(), "Data Facebook")  # crea "Data Facebook" junto al script
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"meta_{datetime.now():%Y-%m}.xlsx")  # p.ej. meta_2025-09.xlsx

BASE = ("https://www.facebook.com/ads/library/"
        "?active_status=active&ad_type=all&country=MX"
        "&is_targeted_country=false&media_type=all"
        "&search_type=keyword_unordered&q=")

# Regex fecha
re_fecha = re.compile(
    r"(?:desde|since)\s+(?:el|the)?\s*("
    r"\d{1,2}\s+(?:ene|feb|mar|abr|may|jun|jul|ago|sep|sept|oct|nov|dic|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-záéíóú]*\s+\d{4}"
    r"|\d{1,2}\s+de\s+[a-záéíóú]+(?:\s+de)?\s+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
    r")",
    re.IGNORECASE
)

# ====== JS: snapshot por tarjeta ======
JS_SNAPSHOT_CARDS = r"""
const xpId = "//*[(self::span or self::div) and (contains(normalize-space(.),'Identificador de la biblioteca:') or contains(normalize-space(.),'Ad library ID:'))]";
const xpPubRel  = ".//a[(starts-with(@href,'https://www.facebook.com/') or starts-with(@href,'/')) and not(contains(@href,'ads/library'))]//span[normalize-space()]";
const xpDateRel = ".//*[(self::span or self::div) and (contains(normalize-space(.),'En circulación desde') or contains(normalize-space(.),'Activo desde') or contains(normalize-space(.),'Comenzó a funcionar desde') or contains(normalize-space(.),'In circulation since') or contains(normalize-space(.),'Started running'))]";
const xpSponsoredRel = ".//*[self::span or self::div][contains(normalize-space(.),'Publicidad') or contains(normalize-space(.),'Sponsored')]";
const xpTextRel = ".//*[(@dir='auto') and (self::div or self::span) and normalize-space()]";
const BLOCKS_RE = /(Identificador de la biblioteca|Ad library ID|En circulación desde|Activo desde|Comenzó a funcionar desde|In circulation since|Started running|Plataformas|Publicidad|Sponsored|Ver detalles|See ad details|Ver detalles del resumen|See summary details|Abrir menú|Abrir menú desplegable|Open menu|Enviar mensaje|Send message|\bCars\b)/i;

function firstText(xp, root){
  const snap = document.evaluate(xp, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  if (snap.snapshotLength > 0) { const n = snap.snapshotItem(0); return (n && n.textContent ? n.textContent.trim() : ""); }
  return "";
}
function firstNode(xp, root){
  const snap = document.evaluate(xp, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  return snap.snapshotLength > 0 ? snap.snapshotItem(0) : null;
}
// *** CAMBIO: no clickeamos <a>, solo botones "Ver más/See more" ***
function expandMore(root){
  const xp = ".//*[@role='button' and (contains(normalize-space(.),'Ver más') or contains(normalize-space(.),'See more'))]";
  const snap = document.evaluate(xp, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  for (let i=0; i<snap.snapshotLength; i++){
    const btn = snap.snapshotItem(i);
    try {
      btn.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true}));
    } catch(e) {}
  }
}
function rect(n){ try { return n.getBoundingClientRect(); } catch(e) { return {top:-1,bottom:-1}; } }
function isInCTA(el){
  try {
    return !!(el.closest('button,[role=button],a[role=button]') ||
              el.closest('[aria-label*="Abrir"],[aria-label*="Open"],[aria-label*="Enviar"],[aria-label*="Send"]'));
  } catch(e){ return false; }
}
function cleanText(s){
  return (s || "").replace(/[\u200B-\u200D\uFEFF]/g,"").replace(/\s+/g," ").trim();
}
function adTextWithin(cont, pub, idNode){
  expandMore(cont);
  const pubNode = firstNode(xpPubRel, cont);
  const sponsoredNode = firstNode(xpSponsoredRel, cont);
  let topY = 0;
  if (pubNode)       topY = Math.max(topY, rect(pubNode).bottom);
  if (sponsoredNode) topY = Math.max(topY, rect(sponsoredNode).bottom);
  if (topY <= 0) topY = rect(cont).top + 1;
  let bottomY = idNode ? rect(idNode).top : rect(cont).bottom;
  const snap = document.evaluate(xpTextRel, cont, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  const lines = [];
  for (let i=0; i<snap.snapshotLength; i++){
    const el = snap.snapshotItem(i);
    const r  = rect(el);
    if (r.top < topY || r.bottom > bottomY) continue;
    if (isInCTA(el)) continue;
    let t = cleanText(el.innerText || el.textContent);
    if (!t) continue;
    if (pub && t === pub) continue;
    if (t === "Activo" || t === "Active") continue;
    if (BLOCKS_RE.test(t)) continue;
    if (/^[·•…]+$/.test(t)) continue;
    lines.push(t);
  }
  const seen = new Set(); const kept = [];
  for (const s of lines){ if (!seen.has(s)) { kept.push(s); seen.add(s); } }
  let body = kept.join("\n").trim();
  if (!body){
    const raw = (cont.innerText || "").split("\n").map(cleanText).filter(Boolean);
    const filtered = raw.filter(s =>
      (!pub || s !== pub) &&
      s !== "Activo" && s !== "Active" &&
      !BLOCKS_RE.test(s) &&
      !/^[·•…]+$/.test(s)
    );
    body = filtered.join("\n").trim();
  }
  return body;
}
const idSnap = document.evaluate(xpId, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
const out = [];
for (let i = 0; i < idSnap.snapshotLength; i++) {
  const idNode = idSnap.snapshotItem(i);
  const idText = (idNode.textContent || "").trim();
  let libId = "";
  let m = idText.match(/Identificador de la biblioteca:\s*([0-9]+)/);
  if (!m) m = idText.match(/Ad library ID:\s*([0-9]+)/i);
  if (m) libId = m[1];
  let anc = idNode, pub = "", dateT = "";
  for (let d = 0; d < 18 && anc; d++) {
    pub = firstText(xpPubRel, anc);
    if (pub) { dateT = firstText(xpDateRel, anc); break; }
    anc = anc.parentNode;
  }
  const cont = anc || idNode;
  const adText = adTextWithin(cont, pub, idNode);
  out.push([libId, pub, dateT, adText]);
}
return out;
"""

# ====== CHROME ======
opts = webdriver.ChromeOptions()
opts.page_load_strategy = "eager"
opts.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
opts.add_experimental_option("useAutomationExtension", False)
opts.add_argument("--disable-extensions")
opts.add_argument("--disable-gpu")
opts.add_argument("--no-first-run")
opts.add_argument("--disable-background-networking")
opts.add_argument("--log-level=3")
opts.add_argument("--disable-notifications")
# Opcional para ahorrar RAM/VRAM:
# opts.add_argument("--headless=new")

service = Service()
service.log_output = open(os.devnull, "w")
service.creationflags = CREATE_NO_WINDOW

driver = webdriver.Chrome(service=service, options=opts)
driver.set_window_size(1400, 900)

# --------- mantener una sola pestaña ----------
def keep_one_tab(driver, main_handle=None):
    main = main_handle or driver.current_window_handle
    for h in driver.window_handles:
        if h != main:
            driver.switch_to.window(h)
            try:
                driver.close()
            except Exception:
                pass
    driver.switch_to.window(main)
    return main
# ---------------------------------------------

rows = []

# -------------------- SCRAPING --------------------
main = driver.current_window_handle  # handle principal
for q in QUERIES:
    try:
        url = BASE + quote(q)
        print(f"\n[OPEN] {url}")
        driver.get(url)

        # Mantener 1 pestaña y bloquear nuevas aperturas
        main = keep_one_tab(driver, main)
        driver.execute_script("""
          // Bloque total de nuevas pestañas/ventanas
          window.open = function(){ return null; };
          document.addEventListener('click', function(e){
            const a = e.target.closest('a');
            if (!a) return;
            if (a.target === '_blank') {
              e.preventDefault();
              a.removeAttribute('target');
            }
          }, true);
        """)

        try:
            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.XPATH, "//div")))
        except Exception:
            pass

        cards = driver.execute_script(JS_SNAPSHOT_CARDS)
        ids_seen = set()
        ids, pubs, dates, texts = [], [], [], []

        for libId, pub, dt, body in cards:
            key = libId or f"idx0-{len(ids)}"
            ids_seen.add(key)
            ids.append(libId or "")
            pubs.append(pub or "")
            m = re_fecha.search(dt or "")
            dates.append(m.group(1).strip() if m else (dt or ""))
            txt = (body or "").strip()
            txt = re.sub(r"[ \t]+", " ", txt)
            txt = re.sub(r"(?:\n\s*){2,}", "\n", txt)
            texts.append(txt)

        print(f"[INIT] tarjetas:{len(ids)}")

        stall = 0
        for round_i in range(1, MAX_SCROLLS + 1):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # guardián por si algo abre pestaña
            main = keep_one_tab(driver, main)

            start = time.time()
            added = 0
            while True:
                if time.time() - start >= INNER_WAIT_MAX:
                    break
                time.sleep(INNER_POLL_INTERVAL)
                curr = driver.execute_script(JS_SNAPSHOT_CARDS)
                for idx, (libId, pub, dt, body) in enumerate(curr):
                    key = libId or f"idx{round_i}-{idx}"
                    if key in ids_seen:
                        continue
                    ids_seen.add(key)
                    ids.append(libId or "")
                    pubs.append(pub or "")
                    m = re_fecha.search(dt or "")
                    dates.append(m.group(1).strip() if m else (dt or ""))
                    txt = (body or "").strip()
                    txt = re.sub(r"[ \t]+", " ", txt)
                    txt = re.sub(r"(?:\n\s*){2,}", "\n", txt)
                    texts.append(txt)
                    added += 1
                if added > 0:
                    break
            elapsed = time.time() - start
            print(f"[SCROLL {round_i:02d}] {elapsed:>4.1f}s | +tarjetas:{added} | total:{len(ids)} | {'↑' if added else '⏱ timeout'}")
            if added == 0:
                stall += 1
                if stall >= STALL_ROUNDS:
                    print(f"[STOP] Sin crecimiento en {STALL_ROUNDS} rondas seguidas.")
                    break
            else:
                stall = 0

        n = len(ids)
        print(f"[DONE] '{q}' tarjetas:{n}")
        for i in range(n):
            rows.append({
                "query": q,
                "rank": i+1,
                "ad_library_id": str(ids[i] or ""),  # evita notación científica
                "publisher": pubs[i] or "",
                "fecha_publicacion": dates[i] or "",
                "texto": texts[i] or ""
            })

    except Exception as e:
        print(f"[SKIP] '{q}' falló: {e.__class__.__name__}: {e}")
        continue

driver.quit()

# -------------------- EXPORTAR: XLSX mensual en 'Data Facebook' --------------------
if rows:
    import pandas as pd
    df = pd.DataFrame(rows, columns=["query","rank","ad_library_id","publisher","fecha_publicacion","texto"])
    df["ad_library_id"] = df["ad_library_id"].astype(str)
    df.to_excel(OUTPUT_FILE, index=False, sheet_name="Anuncios")
    print(f"\n[OK] XLSX guardado en: {OUTPUT_FILE}")
else:
    print("\n[WARN] No se capturaron resultados.")

# -------------------- FIN --------------------
ELAPSED = time.perf_counter() - START_TS
h, rem = divmod(int(ELAPSED + 0.5), 3600)
m, s = divmod(rem, 60)
print(f"[TOTAL] {ELAPSED:.1f}s  (~{h:02d}:{m:02d}:{s:02d})")
