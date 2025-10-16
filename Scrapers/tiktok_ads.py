# tiktok_topads_to_csv.py
# Requisitos:
#   pip install playwright pandas
#   python -m playwright install chromium
#
# Uso:
#   python tiktok_topads_to_csv.py

import asyncio
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
import pandas as pd

# ---------- CONFIG ----------
TARGET = "https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en?period=30&region=MX"
ENDPOINT_PATH = "/creative_radar_api/v1/top_ads/v2/list"
OUT_CSV = "Data Tiktok/topads_only_csv.csv"

BRANDS = [
    "Honda", "Toyota", "Nissan", "GM", "Volkswagen", "Kia", "Mazda",
    "Fiat", "MG", "Ford", "Hyundai", "Chirey", "Renault", "JAC",
    "Mitsubishi", "BAIC", "JMC", "Changan", "BYD", "Chevrolet"
]


HEADLESS = True
PAGE_TIMEOUT = 30_000          # ms para page.goto
SEARCH_TIMEOUT = 10.0         # segundos para esperar la respuesta de la API por búsqueda
INPUT_WAIT = 2.0              # segundos tras escribir antes de esperar la respuesta
PAGE_LIMIT = 20               # limit param (puedes bajar si quieres)
# ----------------------------

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def build_url(params: dict) -> str:
    return "https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list?" + urlencode(params)


def pick_best_video_url(video_url_map: dict):
    """Elegir la mejor resolución disponible (numérica más alta)."""
    if not isinstance(video_url_map, dict) or not video_url_map:
        return None
    try:
        best = max(
            (k for k in video_url_map.keys() if any(ch.isdigit() for ch in k)),
            key=lambda k: int(''.join(ch for ch in k if ch.isdigit()) or 0),
        )
        return video_url_map.get(best) or next(iter(video_url_map.values()))
    except Exception:
        return next(iter(video_url_map.values()))


async def main():
    rows = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, args=["--no-sandbox"])
        # Usa un contexto persistente si quieres mantener cookies entre ejecuciones:
        context = await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )

        page = await context.new_page()

        # Cola para respuestas detectadas (tuplas: (url, json_obj))
        resp_queue: asyncio.Queue = asyncio.Queue()

        async def on_response(resp):
            try:
                url = resp.url
                # filtrar por endpoint path (puede venir con querystring)
                if ENDPOINT_PATH in url:
                    # leer texto (a veces resp.json() lanza si no es JSON).
                    txt = await resp.text()
                    try:
                        j = json.loads(txt)
                    except Exception:
                        return
                    # poner en la cola para procesarlo desde el loop principal
                    await resp_queue.put((url, j))
            except Exception:
                return

        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        print("Abriendo página:", TARGET)
        try:
            await page.goto(TARGET, wait_until="load", timeout=PAGE_TIMEOUT)
        except PWTimeout:
            print("Warning: page.goto timeout; intentando continuar...")

        # Intentar cerrar posibles modales que bloqueen input
        async def try_close_modals():
            # selectores comunes de modales; pueden no existir
            candidates = [
                "button[aria-label='Close']",
                "button.close",
                ".byted-modal-footer button",
                ".byted-modal-body button",
                ".modal-close",
                "button[data-e2e='close']",
            ]
            for sel in candidates:
                try:
                    elems = await page.query_selector_all(sel)
                    for e in elems:
                        try:
                            await e.click(timeout=500)
                        except Exception:
                            pass
                except Exception:
                    pass

        await try_close_modals()

        # localizar el input de búsqueda (probamos varios selectores)
        SEARCH_INPUT_SELECTORS = [
            "input[type=search]",
            "input[placeholder*='Search']",
            "input[placeholder*='search']",
            "input[aria-label*='Search']",
            'input[placeholder*="Brand"]',
            ".search-input input",
            "input"
        ]

        search_input = None
        for sel in SEARCH_INPUT_SELECTORS:
            try:
                # wait short tiempo para que aparezca si existe
                el = await page.query_selector(sel)
                if el:
                    search_input = el
                    # probar que sea interactuable
                    try:
                        await el.scroll_into_view_if_needed()
                        await el.click(timeout=1000)
                        break
                    except Exception:
                        # no salió, pero igual lo usaremos con fill
                        break
            except Exception:
                continue

        if not search_input:
            # fallback: ejecutamos JS para buscar inputs visibles
            search_input = await page.query_selector("input")
            if not search_input:
                print("No se encontró input de búsqueda. Intenta HEADLESS=False para interactuar manualmente.")
                await browser.close()
                return

        # función que espera y consume respuestas para la marca concreta
        async def wait_for_brand_results(brand: str, timeout: float = SEARCH_TIMEOUT):
            """Espera respuestas en resp_queue relacionadas con la marca (por querystring o por contenido)."""
            deadline = time.time() + timeout
            collected = []
            # Poll hasta la fecha límite
            while time.time() < deadline:
                try:
                    wait_time = max(0.1, deadline - time.time())
                    url, j = await asyncio.wait_for(resp_queue.get(), timeout=wait_time)
                except asyncio.TimeoutError:
                    break
                # comprobar si el url tiene el keyword=brand (case-insensitive)
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                kw_vals = [v.lower() for v in qs.get("keyword", [])]
                if any(brand.lower() == v or brand.lower() in v for v in kw_vals):
                    collected.append((url, j))
                    # si el json trae materiales con items, podemos devolverlos inmediatamente
                    mats = (j.get("data") or {}).get("materials") or []
                    if mats:
                        return collected
                    # si code != 0, igualmente lo devolvemos
                    code = j.get("code")
                    if code is not None and code != 0:
                        return collected
                else:
                    # si no coincide, descartamos o guardamos para debug
                    # (podemos ignorar)
                    continue
            return collected

        # loop de marcas
        for brand in BRANDS:
            print(f"\n=== Procesando marca: {brand} ===")
            # limpiar cola remanente (no obligatorio, pero ayuda)
            while not resp_queue.empty():
                try:
                    resp_queue.get_nowait()
                except Exception:
                    break

            # preparar URL alternativa (por si prefieres hacer fetch directo dentro de la página)
            # NO usamos fetch directo aquí: queremos replicar UI y capturar la respuesta que la página genera.
            try:
                # enfocar y escribir
                await search_input.fill("")  # limpiar
                # escribir la marca
                await search_input.fill(brand)
                # esperar un momento para que la UI haga la petición
                await asyncio.sleep(INPUT_WAIT)
                # presionar Enter para forzar búsqueda si corresponde
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    # fallback intentar click en input para confirmar
                    try:
                        await search_input.click()
                    except Exception:
                        pass

                # esperar y recolectar respuestas relacionadas con la marca
                collected = await wait_for_brand_results(brand, timeout=SEARCH_TIMEOUT)

                if not collected:
                    # intentar un segundo intento: presionar Enter otra vez
                    print(f"  No se detectó respuesta para {brand} en el primer intento. Reintentando...")
                    try:
                        await page.keyboard.press("Enter")
                    except Exception:
                        pass
                    collected = await wait_for_brand_results(brand, timeout=SEARCH_TIMEOUT)

                # procesar lo recolectado
                found_any = False
                for url, j in collected:
                    code = j.get("code")
                    if code is not None and code != 0:
                        print(f"  API devolvió code: {code} msg: {j.get('msg')}")
                        # si devolvió 'no permission' seguiremos (no crash), pero no habrá materials
                    mats = (j.get("data") or {}).get("materials") or []
                    if mats:
                        found_any = True
                    for m in mats:
                        vinfo = m.get("video_info") or {}
                        video_best = pick_best_video_url(vinfo.get("video_url") or {})
                        row = {
                            "brand_query": brand,
                            "ad_id": m.get("id"),
                            "ad_title": m.get("ad_title"),
                            "brand_name": m.get("brand_name"),
                            "likes": m.get("like"),
                            "ctr": m.get("ctr"),
                            "cost": m.get("cost"),
                            "video_best": video_best,
                            "cover": vinfo.get("cover"),
                            "duration": vinfo.get("duration"),
                            "width": vinfo.get("width"),
                            "height": vinfo.get("height"),
                            "raw_code": code,
                            "raw_msg": j.get("msg"),
                            "request_url": url,
                        }
                        rows.append(row)

                if not found_any:
                    print(f"  No materials encontrados para {brand} (puede ser code=40101/no permission).")
                else:
                    print(f"  Agregados {sum(1 for r in rows if r['brand_query']==brand)} filas para {brand}.")

                # pequeña espera antes de la siguiente marca
                await asyncio.sleep(0.4)

            except Exception as ex:
                print(f"  Error al procesar {brand}: {ex}")

        # cerrar navegador
        await browser.close()

    # Guardar CSV (único output)
    if rows:
        df = pd.DataFrame(rows)
        # reordenar columnas para confort
        cols = ["brand_query", "ad_id", "ad_title", "brand_name", "likes", "ctr", "cost",
                "duration", "width", "height", "video_best", "cover",
                "raw_code", "raw_msg", "request_url"]
        df = df[[c for c in cols if c in df.columns]]
        df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
        print(f"\n[OK] CSV guardado: {OUT_CSV} (filas: {len(df)})")
    else:
        print("\n[WARN] No se extrajeron filas. Revisa si la API devolvió permisos (code 40101) o intenta HEADLESS=False para ver la UI.")
        # si quieres debug, puedes imprimir la última respuesta en consola (no lo hago por petición tuya)

if __name__ == "__main__":
    asyncio.run(main())
