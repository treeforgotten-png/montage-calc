#!/usr/bin/env python3
"""
PlayAsia Figures Scraper
Парсит фигурки от $30 (в наличии + предзаказы) с play-asia.com
Цена итоговая = цена_USD × 100 × 2.5
Результат: figures.csv

Скачать:
    curl -O https://raw.githubusercontent.com/treeforgotten-png/montage-calc/claude/parse-playasia-figures-QvKDk/scraper.py
    # или
    wget https://raw.githubusercontent.com/treeforgotten-png/montage-calc/claude/parse-playasia-figures-QvKDk/scraper.py

Запуск:
    pip install requests beautifulsoup4 lxml
    python3 scraper.py

Опционально:
    python3 scraper.py --pages 5        # только первые 5 страниц
    python3 scraper.py --debug          # сохранить HTML страниц для отладки
    python3 scraper.py --output out.csv
"""

import argparse
import csv
import logging
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL     = "https://www.play-asia.com"
CATEGORY_URL = "https://www.play-asia.com/collectibles-figures/14/70d7"

# avail=1 → в наличии, avail=2 → предзаказ
AVAILABILITY_FILTERS = {
    "in_stock":  {"avail": "1"},
    "pre_order": {"avail": "2"},
}

MIN_PRICE_USD = 30.0   # фильтр: только от $30
PRICE_MULT    = 100 * 2.5  # = 250

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":                  "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language":         "en-US,en;q=0.9",
    "Accept-Encoding":         "gzip, deflate, br",
    "Connection":              "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":          "document",
    "Sec-Fetch-Mode":          "navigate",
    "Sec-Fetch-Site":          "none",
    "Cache-Control":           "max-age=0",
}

REQUEST_DELAY = 1.5
MAX_RETRIES   = 3


# ─── HTTP ─────────────────────────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def get_page(session: requests.Session, url: str, params: dict = None,
             debug: bool = False, debug_tag: str = "") -> BeautifulSoup | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=30)

            if resp.status_code == 403:
                log.warning("403 Forbidden — PlayAsia блокирует запрос. "
                            "Попробуйте запустить через VPN.")
                return None
            if resp.status_code == 429:
                wait = 30 * attempt
                log.warning("429 Too Many Requests. Ждём %d сек…", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()

            if debug and debug_tag:
                Path(f"debug_{debug_tag}.html").write_text(resp.text, encoding="utf-8")

            return BeautifulSoup(resp.text, "lxml")

        except requests.RequestException as e:
            log.warning("Попытка %d/%d: %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return None


# ─── Парсинг ───────────────────────────────────────────────────────────────────────

def get_total_pages(soup: BeautifulSoup) -> int:
    last_link = soup.select_one("a.last-page, a[title='Last Page'], .pagination a:last-of-type")
    if last_link:
        m = re.search(r"/(\d+)/?$", last_link.get("href", ""))
        if m:
            return int(m.group(1))

    total_span = soup.select_one(".total-pages, [data-total-pages]")
    if total_span:
        txt = total_span.get_text(strip=True) or total_span.get("data-total-pages", "")
        m = re.search(r"\d+", txt)
        if m:
            return int(m.group())

    for a in reversed(soup.select(".pagination a, .pager a")):
        m = re.search(r"(\d+)", a.get_text(strip=True))
        if m:
            return int(m.group(1))

    return 1


def extract_usd(price_text: str) -> float | None:
    """Извлечь числовое значение USD из строки цены, например 'US$ 45.99' → 45.99"""
    m = re.search(r"[\$US\s]*([\d,]+\.?\d*)", price_text.replace(",", ""))
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_figure(card: BeautifulSoup) -> dict | None:
    # Ссылка
    link_el = card.select_one("a.item-link, a[href*='play-asia.com'], h2 a, h3 a, .title a")
    if not link_el:
        link_el = card.find("a", href=re.compile(r"/[A-Za-z0-9_-]+/13/"))
    if not link_el:
        link_el = card.find("a")
    if not link_el:
        return None

    url = link_el.get("href", "").strip()
    if url and not url.startswith("http"):
        url = urljoin(BASE_URL, url)

    # Название
    title_el = (
        card.select_one(".title, .product-title, h2, h3, [itemprop='name']")
        or link_el
    )
    title = title_el.get_text(" ", strip=True)

    # Изображение
    img_el = card.select_one("img[src], img[data-src], img[data-lazy-src]")
    image_url = ""
    if img_el:
        image_url = (
            img_el.get("data-src")
            or img_el.get("data-lazy-src")
            or img_el.get("src")
            or ""
        ).strip()
        if image_url.startswith("//"):
            image_url = "https:" + image_url
        elif image_url.startswith("/"):
            image_url = BASE_URL + image_url

    # Цена
    price_el = card.select_one(
        ".price, [itemprop='price'], .product-price, .sale-price, "
        "[class*='price'], span.our_price_display"
    )
    price_raw = re.sub(r"\s+", " ", price_el.get_text(" ", strip=True)).strip() if price_el else ""

    price_usd = extract_usd(price_raw)
    if price_usd is None or price_usd < MIN_PRICE_USD:
        return None  # пропускаем дешевле $30

    price_final = round(price_usd * PRICE_MULT)

    # Доступность
    avail_el = card.select_one(
        ".availability, .stock-status, [class*='avail'], [class*='stock']"
    )
    availability = avail_el.get_text(" ", strip=True) if avail_el else ""

    if not title and not url:
        return None

    return {
        "title":        title,
        "price_usd":    price_usd,
        "price_final":  price_final,
        "availability": availability,
        "image_url":    image_url,
        "url":          url,
    }


def parse_listing_page(soup: BeautifulSoup) -> list[dict]:
    selectors = [
        "div.item", "li.item",
        "div.product-item", "div.product-card",
        "[class*='product-item']", "[class*='item-box']",
        "ul.product-list > li", "div.listing-product",
    ]

    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            log.debug("Найдено %d карточек по селектору: %s", len(cards), sel)
            break

    if not cards:
        log.warning("Карточки не найдены. Проверьте debug_*.html для анализа структуры.")
        return []

    figures = []
    for card in cards:
        f = parse_figure(card)
        if f:
            figures.append(f)
    return figures


# ─── Сбор данных ──────────────────────────────────────────────────────────────

def scrape_availability(session, avail_label, avail_params, max_pages, debug) -> list[dict]:
    results = []
    page    = 1
    total   = 1

    log.info("=== Сбор: %s ===", avail_label)

    while True:
        if max_pages and page > max_pages:
            break

        params = {**avail_params, "page": page}
        log.info("[%s] Страница %d/%d…", avail_label, page, total)

        soup = get_page(session, CATEGORY_URL, params=params,
                        debug=debug, debug_tag=f"{avail_label}_p{page}")
        if soup is None:
            log.error("Не удалось загрузить страницу %d. Прерываем.", page)
            break

        if page == 1:
            total = get_total_pages(soup)
            if max_pages:
                total = min(total, max_pages)
            log.info("[%s] Всего страниц: %d", avail_label, total)

        items = parse_listing_page(soup)
        log.info("[%s] Стр. %d: %d фигурок ≥ $%.0f", avail_label, page, len(items), MIN_PRICE_USD)
        results.extend(items)

        if page >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    log.info("[%s] Итого: %d", avail_label, len(results))
    return results


def deduplicate(figures: list[dict]) -> list[dict]:
    seen, unique = set(), []
    for f in figures:
        key = f.get("url") or f.get("title")
        if key and key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ─── Запись CSV ───────────────────────────────────────────────────────────────────

CSV_FIELDS = ["title", "price_usd", "price_final", "availability", "image_url", "url"]

def save_csv(figures: list[dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(figures)
    log.info("Сохранено в %s", path.resolve())


# ─── main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PlayAsia Figures Scraper")
    parser.add_argument("--pages",  type=int, default=0,
                        help="Макс. кол-во страниц на фильтр (0 = все)")
    parser.add_argument("--output", default="figures.csv",
                        help="Выходной CSV-файл")
    parser.add_argument("--debug",  action="store_true",
                        help="Сохранять HTML страниц для отладки")
    args = parser.parse_args()

    session     = make_session()
    all_figures: list[dict] = []

    for label, params in AVAILABILITY_FILTERS.items():
        figures = scrape_availability(session, label, params, args.pages, args.debug)
        for f in figures:
            if not f.get("availability"):
                f["availability"] = "In Stock" if label == "in_stock" else "Pre-Order"
        all_figures.extend(figures)

    all_figures = deduplicate(all_figures)
    log.info("Уникальных фигурок: %d", len(all_figures))

    out_path = Path(args.output)
    save_csv(all_figures, out_path)

    in_stock  = sum(1 for f in all_figures if "stock" in f.get("availability","").lower()
                    or f.get("availability") == "In Stock")
    preorders = len(all_figures) - in_stock

    print(f"\n{'─'*52}")
    print(f"  Фигурок от ${MIN_PRICE_USD:.0f}:  {len(all_figures)}")
    print(f"  В наличии:       {in_stock}")
    print(f"  Предзаказы:      {preorders}")
    print(f"  Формула цены:    USD × {PRICE_MULT:.0f}  (×100 ×2.5)")
    print(f"  Файл:            {out_path.resolve()}")
    print(f"{'─'*52}\n")


if __name__ == "__main__":
    main()
