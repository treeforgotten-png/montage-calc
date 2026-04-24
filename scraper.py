#!/usr/bin/env python3
"""
PlayAsia Figures Scraper
Парсит все фигурки в наличии и предзаказы с play-asia.com
Результат: figures.json

Запуск:
    pip install requests beautifulsoup4 lxml
    python3 scraper.py

Опционально:
    python3 scraper.py --pages 5        # только первые 5 страниц
    python3 scraper.py --debug          # сохранить HTML страниц для отладки
    python3 scraper.py --output out.json
"""

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─── Конфигурация ────────────────────────────────────────────────────────────

BASE_URL = "https://www.play-asia.com"

# Категория «Collectibles & Figures»
CATEGORY_URL = "https://www.play-asia.com/collectibles-figures/14/70d7"

# Availability-фильтры PlayAsia:
#   В наличии  → avail=1
#   Предзаказ  → avail=2
AVAILABILITY_FILTERS = {
    "in_stock":   {"avail": "1"},
    "pre_order":  {"avail": "2"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

REQUEST_DELAY = 1.5   # сек между запросами (будьте вежливы к серверу)
MAX_RETRIES   = 3


# ─── HTTP-сессия ─────────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def get_page(session: requests.Session, url: str, params: dict = None,
             debug: bool = False, debug_tag: str = "") -> BeautifulSoup | None:
    """Загрузить страницу и вернуть BeautifulSoup. При неудаче — None."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=30)
            log.debug("GET %s → %s", resp.url, resp.status_code)

            if resp.status_code == 403:
                log.warning("403 Forbidden — PlayAsia может блокировать бота. "
                            "Попробуйте запустить через VPN или сделайте паузу.")
                return None
            if resp.status_code == 429:
                wait = 30 * attempt
                log.warning("429 Too Many Requests. Ждём %s сек…", wait)
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


# ─── Парсинг продуктов ───────────────────────────────────────────────────────

def get_total_pages(soup: BeautifulSoup) -> int:
    """Определить кол-во страниц пагинации."""
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


def parse_figure(card: BeautifulSoup) -> dict | None:
    """Извлечь данные одной фигурки из карточки товара."""

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

    title_el = (
        card.select_one(".title, .product-title, h2, h3, [itemprop='name']")
        or link_el
    )
    title = title_el.get_text(" ", strip=True)

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

    price_el = card.select_one(
        ".price, [itemprop='price'], .product-price, .sale-price, "
        "[class*='price'], span.our_price_display"
    )
    price = price_el.get_text(" ", strip=True) if price_el else ""
    price = re.sub(r"\s+", " ", price).strip()

    desc_el = card.select_one(
        ".subtitle, .description, .product-desc, .item-desc, "
        "[class*='subtitle'], [class*='description']"
    )
    description = desc_el.get_text(" ", strip=True) if desc_el else ""

    avail_el = card.select_one(
        ".availability, .stock-status, [class*='avail'], [class*='stock']"
    )
    availability = avail_el.get_text(" ", strip=True) if avail_el else ""

    if not title and not url:
        return None

    return {
        "title":        title,
        "description":  description,
        "price":        price,
        "availability": availability,
        "image_url":    image_url,
        "url":          url,
    }


def parse_listing_page(soup: BeautifulSoup) -> list[dict]:
    """Парсит все карточки с одной страницы листинга."""
    figures = []

    selectors = [
        "div.item",
        "li.item",
        "div.product-item",
        "div.product-card",
        "[class*='product-item']",
        "[class*='item-box']",
        "ul.product-list > li",
        "div.listing-product",
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

    for card in cards:
        figure = parse_figure(card)
        if figure:
            figures.append(figure)

    return figures


# ─── Основной сбор данных ────────────────────────────────────────────────────

def scrape_availability(
    session: requests.Session,
    avail_label: str,
    avail_params: dict,
    max_pages: int,
    debug: bool,
) -> list[dict]:
    """Собрать все фигурки для одного типа доступности."""
    results = []
    page = 1

    log.info("=== Сбор: %s ===", avail_label)

    while True:
        if max_pages and page > max_pages:
            log.info("Достигнут лимит страниц (%d).", max_pages)
            break

        params = {**avail_params, "page": page}
        log.info("[%s] Страница %d…", avail_label, page)

        soup = get_page(
            session, CATEGORY_URL, params=params,
            debug=debug, debug_tag=f"{avail_label}_p{page}"
        )

        if soup is None:
            log.error("Не удалось загрузить страницу %d. Прерываем.", page)
            break

        if page == 1:
            total = get_total_pages(soup)
            log.info("[%s] Всего страниц: %d", avail_label, total)
            if max_pages:
                total = min(total, max_pages)

        items = parse_listing_page(soup)
        log.info("[%s] Страница %d: найдено %d фигурок", avail_label, page, len(items))

        if not items:
            break

        results.extend(items)

        if page >= total:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    log.info("[%s] Итого: %d фигурок", avail_label, len(results))
    return results


# ─── Дедупликация ────────────────────────────────────────────────────────────

def deduplicate(figures: list[dict]) -> list[dict]:
    """Убрать дубликаты по URL."""
    seen = set()
    unique = []
    for f in figures:
        key = f.get("url") or f.get("title")
        if key and key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# ─── Точка входа ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PlayAsia Figures Scraper")
    parser.add_argument("--pages",  type=int, default=0,
                        help="Максимальное кол-во страниц (0 = все)")
    parser.add_argument("--output", default="figures.json",
                        help="Файл для сохранения результатов")
    parser.add_argument("--debug",  action="store_true",
                        help="Сохранять HTML страниц для отладки (debug_*.html)")
    args = parser.parse_args()

    session = make_session()

    all_figures: list[dict] = []

    for label, params in AVAILABILITY_FILTERS.items():
        figures = scrape_availability(
            session,
            avail_label=label,
            avail_params=params,
            max_pages=args.pages,
            debug=args.debug,
        )
        for f in figures:
            if not f.get("availability"):
                f["availability"] = "In Stock" if label == "in_stock" else "Pre-Order"
        all_figures.extend(figures)

    all_figures = deduplicate(all_figures)
    log.info("Уникальных фигурок: %d", len(all_figures))

    out_path = Path(args.output)
    out_path.write_text(
        json.dumps(all_figures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Сохранено в %s", out_path.resolve())

    print(f"\n{'─' * 50}")
    print(f"  Всего фигурок: {len(all_figures)}")
    in_stock  = sum(1 for f in all_figures if "stock" in f.get("availability","").lower()
                    or f.get("availability") == "In Stock")
    preorders = sum(1 for f in all_figures if "pre" in f.get("availability","").lower()
                    or f.get("availability") == "Pre-Order")
    print(f"  В наличии:    {in_stock}")
    print(f"  Предзаказы:   {preorders}")
    print(f"  Файл:         {out_path.resolve()}")
    print(f"{'─' * 50}\n")


if __name__ == "__main__":
    main()
