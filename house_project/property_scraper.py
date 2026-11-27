#!/usr/bin/env python3
"""
property.co.zw scraper for the house-price deep learning project.

Stages (each one is resumable):
  categories list the site's category links (to add more to discover)
  probe     test the parser on ONE page and print what it finds (run this first!)
  discover  walk the category pages (?page=N) and collect listing URLs -> urls.csv
  details   visit each listing once, save raw HTML, parse it -> listings.csv
  images    download up to N photos per listing -> images/<id>/ and image_index.csv
  reparse   rebuild listings.csv from the saved raw HTML (no new requests)

Typical use:
  pip install requests beautifulsoup4 lxml
  python property_scraper.py probe  https://www.property.co.zw/houses-for-sale --contact you@uz.ac.zw
  python property_scraper.py discover --contact you@uz.ac.zw
  python property_scraper.py details  --contact you@uz.ac.zw
  python property_scraper.py images   --contact you@uz.ac.zw --max-images 5

Politeness built in: robots.txt is checked, requests are spaced by a randomised
delay, the User-Agent identifies you, and the script stops if the site starts
blocking (403/429). It does NOT try to get around blocking: if that happens,
stop and ask the site for permission or for a data export.
"""
import argparse, csv, gzip, hashlib, json, os, random, re, shutil, sys, time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.property.co.zw"

# category label -> path. Check these slugs in your browser; add/remove as needed
# (e.g. an apartments or cluster-houses category if the site has one).
CATEGORIES = {
    "house": "/houses-for-sale",
    "townhouse": "/townhouses-for-sale",
    "flat": "/garden-flats-for-sale",
    "land": "/residential-land-stands-for-sale",
}

# What a listing-detail URL looks like. Adjust after running `probe` if needed.
DEFAULT_LINK_REGEX = r"/for-sale/[^/?#]*\d{4,}[^/?#]*/?$"
SKIP_LINK_WORDS = ("uploadedfiles", "login", "register", "agent", "agency", "showdays", "contact", "about", "blog", "mailto:", "tel:")

FEATURE_JUNK = re.compile(r"loan|^\d+ years?$|purchase|refinance|switch banks|employment|salaried|self-employed|home maker|retired|type of property|^(house|apartment|commercial|land)$|for sale|^harare|^\d+ bed", re.I)

FLAGS = {  # keyword flags built from title + description + feature lists
    "borehole": r"bore\s?hole", "solar": r"solar", "pool": r"swimming pool|\bpool\b",
    "cottage": r"cottage|flatlet|granny flat", "walled": r"\bwalled\b|perimeter wall",
    "gated": r"\bgated\b|electric gate|security gate", "electric_fence": r"electric fence",
    "title_deeds": r"title deeds?|freehold", "cession": r"cession", "ensuite": r"en-?suite",
    "tiled": r"tiled", "fitted_kitchen": r"fitted kitchen", "staff_quarters": r"staff quarters?|servants?",
    "garden": r"garden", "alarm": r"alarm", "backup_power": r"generator|inverter|backup power",
    "water_tank": r"water tank|jojo|\btank\b", "cluster_or_complex": r"cluster|complex|townhouse",
    "double_storey": r"double.?storey", "needs_work": r"incomplete|unfinished|under construction|dilapidated|renovat",
    "commercial_use": r"commercial|clinic|guest ?house",
    "garage": r"garage|carport", "fireplace": r"fire ?place", "verandah": r"veranda", "study": r"study|home office",
}

COLUMNS = (
    ["listing_id", "reference", "listing_url", "category", "property_type_url", "date_posted", "date_collected",
     "title", "price_raw", "price_value", "currency", "location_raw", "suburb", "area", "city", "latitude", "longitude",
     "bedrooms", "bathrooms", "garages", "floor_size_m2", "land_size_m2", "agent_name", "amenities", "description",
     "n_images_found", "image_urls"]
    + ["flag_" + k for k in FLAGS]
)

# ----------------------------------------------------------------------------- fetching

LIVE_LINE = False

def say(*args):
    """print(), but first wipe the live status line (photos stage) so messages don't get glued onto it."""
    if LIVE_LINE:
        sys.stdout.write("\r" + " " * 125 + "\r")
    print(*args)

class Blocked(Exception):
    pass

class Fetcher:
    def __init__(self, contact, delay):
        self.s = requests.Session()
        self.ua = f"UZ-Coursework-Scraper/1.0 (student research; contact: {contact})"
        self.s.headers.update({"User-Agent": self.ua, "Accept-Language": "en"})
        self.delay = delay
        self.last = 0.0
        self.strikes = 0
        self.robots = RobotFileParser()
        try:
            r = self.s.get(BASE + "/robots.txt", timeout=20)
            self.robots.parse(r.text.splitlines() if r.ok else [])
            cd = self.robots.crawl_delay("*") or self.robots.crawl_delay(self.ua)
            if cd:
                self.delay = max(self.delay, float(cd))
                print(f"robots.txt crawl-delay -> using {self.delay}s")
        except Exception as e:
            print("Could not read robots.txt:", e)

    def allowed(self, url):
        return self.robots.can_fetch("*", url)

    def _wait(self, delay):
        gap = (delay if delay is not None else self.delay) * random.uniform(0.8, 1.5)
        left = self.last + gap - time.time()
        if left > 0:
            time.sleep(left)

    def get(self, url, binary=False, delay=None):
        self.last_status = None
        if not self.allowed(url):
            say("  robots.txt disallows:", url)
            return None
        for attempt in range(4):
            self._wait(delay)
            try:
                r = self.s.get(url, timeout=40)
            except requests.RequestException as e:
                say("  network error:", e)
                self.last = time.time()
                time.sleep(10 * (attempt + 1))
                continue
            self.last = time.time()
            self.last_status = r.status_code
            if r.status_code in (403, 429, 503):
                self.strikes += 1
                say(f"  HTTP {r.status_code} (strike {self.strikes}) for {url}")
                if self.strikes >= 3:
                    raise Blocked("The site keeps refusing requests. Stop, wait, and consider asking for permission.")
                time.sleep(60 * (attempt + 1))
                continue
            if r.status_code == 404:
                say(f"  HTTP 404 (not found): {url}")
                return None
            if r.ok:
                self.strikes = 0
                return r.content if binary else r.text
            say(f"  HTTP {r.status_code} for {url} (attempt {attempt + 1})")
        return None

# ----------------------------------------------------------------------------- parsing

def clean(t):
    return re.sub(r"[ \t\r\f\v]+", " ", t or "").strip()

def to_float(s):
    try:
        return float(str(s).replace(",", "").replace(" ", ""))
    except ValueError:
        return None

def find_listing_links(html, page_url, link_regex):
    soup = BeautifulSoup(html, "lxml")
    out, rx = [], re.compile(link_regex, re.I)
    for a in soup.find_all("a", href=True):
        href = urldefrag(urljoin(page_url, a["href"]))[0]
        p = urlparse(href)
        if p.netloc.replace("www.", "") != urlparse(BASE).netloc.replace("www.", ""):
            continue
        if any(w in href.lower() for w in SKIP_LINK_WORDS) or "page=" in p.query:
            continue
        if rx.search(p.path) and p.path.strip("/") not in [c.strip("/") for c in CATEGORIES.values()]:
            href = href.split("?")[0]
            if href not in out:
                out.append(href)
    return out

def jsonld(soup):
    out = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                out.update(item)
    return out

def parse_price(text):
    m = re.search(r"(US\$|USD|ZWG|ZiG|ZWL|\$)\s?(\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)", text, re.I)
    if not m:
        m2 = re.search(r"(\d{1,3}(?:[ ,]\d{3})+|\d+)\s?(USD|ZWG|ZiG)\b", text, re.I)
        if not m2:
            return None, None, None
        raw, cur, num = m2.group(0), m2.group(2), m2.group(1)
    else:
        raw, cur, num = m.group(0), m.group(1), m.group(2)
    currency = "USD" if cur.upper() in ("US$", "USD", "$") else "ZWG"
    return raw, to_float(num), currency

def size_m2(label_rx, text):
    m = re.search(label_rx + r"\D{0,14}?([\d][\d,\.]*)\s*(m²|m2|sqm|sq\.?\s?m|ha\b|hectares?)", text, re.I)
    if not m:
        return None
    v = to_float(m.group(1).rstrip(".,"))
    if v is not None and m.group(2).lower().startswith(("ha", "hect")):
        v *= 10000
    return v

def count_after(word_rx, text):
    for pat in (word_rx + r"\s*[:\-]?\s*(\d+)", r"(\d+)\s*[- ]?(?:car\s*)?" + word_rx):
        m = re.search(pat, text, re.I)
        if m:
            return int(m.group(1))
    return None

def ld_listing(soup):
    """The page embeds schema.org JSON-LD with price, beds, baths, floor size, coordinates and date posted."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "", strict=False)
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "RealEstateListing":
                return item
    return {}

def area_value(text):
    m = re.search(r"([\d][\d,]*(?:\.\d+)?)\s*(m²|m2|sqm|ha\b|hectares?|acres?)", text or "", re.I)
    if not m:
        return None
    v, u = to_float(m.group(1)), m.group(2).lower()
    if v is None:
        return None
    if u.startswith(("ha", "hect")):
        v *= 10000
    elif u.startswith("acre"):
        v *= 4046.86
    return v

def first_int(el):
    m = re.search(r"\d+", el.get_text(" ")) if el else None
    return int(m.group()) if m else None

def parse_listing(html, url, category):
    soup = BeautifulSoup(html, "lxml")
    ld = ld_listing(soup)
    about = ld.get("about") or {}
    offers = ld.get("offers") or {}
    geo = about.get("geo") or {}

    h1 = soup.find("h1")
    title = clean(h1.get_text(" ")) if h1 else clean(ld.get("name", ""))

    # price (page shows "$670,000"; JSON-LD has the clean number and currency)
    pv = soup.find(id="priceVal")
    price_raw = clean(pv.get_text(" ")) if pv else None
    price_value = to_float(offers.get("price")) if offers.get("price") else None
    currency = offers.get("priceCurrency")
    r2, v2, c2 = parse_price(price_raw or "")
    price_raw = price_raw or r2
    price_value = price_value if price_value is not None else v2
    currency = currency or c2

    # location: "Suburb, Region, City"
    addr = soup.select_one(".address")
    loc = clean(addr.get_text(" ")) if addr else ""
    if not loc and isinstance(about.get("address"), dict):
        loc = ", ".join(str(about["address"][k]) for k in ("addressLocality", "addressRegion") if about["address"].get(k))
    parts = [clean(x) for x in loc.split(",")]
    suburb = parts[0] if parts else ""
    area = parts[1] if len(parts) > 1 else ""
    city = parts[2] if len(parts) > 2 else ""

    # beds / baths / floor and land area (icon block under the title)
    box = soup.select_one(".bed-bath-area-container")
    beds = first_int(box.select_one(".bed")) if box and box.select_one(".bed") else about.get("numberOfBedrooms")
    baths = first_int(box.select_one(".bath")) if box and box.select_one(".bath") else about.get("numberOfBathroomsTotal")
    floor_sz = land_sz = None
    if box:
        for div in box.select(".area"):
            val = area_value(div.get_text(" "))
            land_icon = div.find("img", alt=re.compile("land", re.I))
            if land_icon:
                land_sz = val
            elif div.select_one("i.fa-building") or div.find("img", alt=re.compile("floor|building", re.I)):
                floor_sz = val
    if floor_sz is None and isinstance(about.get("floorSize"), dict):
        floor_sz = to_float(about["floorSize"].get("value"))

    # description (the agent's own text) and amenities
    description = ""
    dh = soup.find("h2", string=re.compile("Description", re.I))
    art = dh.parent.select_one(".article") if dh else None
    if art:
        description = clean(art.get_text("\n", strip=True))
    if not description:
        description = clean(ld.get("description", ""))
    amenities = []
    ah = soup.find("h2", string=re.compile("Amenities", re.I))
    if ah:
        for d in ah.parent.find_all("div", class_="vcenterFlex"):
            t = clean(d.get_text(" "))
            if t and not d.find("img") and t not in amenities:
                amenities.append(t)

    seller = offers.get("seller") or {}
    agent = clean(seller.get("name", ""))
    if not agent:
        h3 = soup.find("h3", class_="col-span-3")
        agent = clean(h3.get_text(" ")) if h3 else ""

    # garages: from the text ("double garage", "2 garages")
    gtext = description + " " + " ".join(amenities)
    garages = count_after(r"garages?", gtext)
    if garages is None:
        garages = 3 if re.search(r"triple\s+(?:lock.?up\s+)?garage", gtext, re.I) else 2 if re.search(r"double\s+(?:lock.?up\s+)?garage", gtext, re.I) else (1 if re.search(r"garage|carport", gtext, re.I) else None)

    # photos: the gallery slides, normalised to the full-size original and de-duplicated
    imgs = []
    def add(u):
        if not u:
            return
        u = urljoin(url, u.strip().split(" ")[0])
        if not re.search(r"/uploadedfiles/.+\.webp(\?|$)", u, re.I):
            return
        u = re.sub(r"_thumbnail\d+(?=\.\w+)", "", u.split("?")[0])
        if u not in imgs:
            imgs.append(u)
    for im in soup.select(".swiper-detail .swiper-slide img"):
        add(im.get("data-src") or im.get("src"))
    if not imgs:
        for u in about.get("image", []) if isinstance(about.get("image"), list) else []:
            add(u)

    path = urlparse(url).path
    code = re.search(r"-([a-z]+\d+)/?$", path, re.I)
    ptype = re.search(r"/for-sale/(.+)-[a-z]+\d+/?$", path, re.I)
    corpus = " ".join([title, description, " ".join(amenities)])
    row = {
        "listing_id": code.group(1).lower() if code else hashlib.md5(url.encode()).hexdigest()[:10],
        "reference": ld.get("identifier", ""), "listing_url": url, "category": category,
        "property_type_url": ptype.group(1) if ptype else "",
        "date_posted": ld.get("datePosted", ""),
        "date_collected": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "title": title, "price_raw": price_raw, "price_value": price_value, "currency": currency,
        "location_raw": loc, "suburb": suburb, "area": area, "city": city,
        "latitude": geo.get("latitude"), "longitude": geo.get("longitude"),
        "bedrooms": beds, "bathrooms": baths, "garages": garages,
        "floor_size_m2": floor_sz, "land_size_m2": land_sz,
        "agent_name": agent, "amenities": "|".join(amenities), "description": description,
        "n_images_found": len(imgs), "image_urls": "|".join(imgs),
    }
    for k, rx in FLAGS.items():
        row["flag_" + k] = int(bool(re.search(rx, corpus, re.I)))
    return row

# ----------------------------------------------------------------------------- storage helpers

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def append_csv(path, cols, row):
    """Append one row. If the file is locked (e.g. open in Excel) wait and retry instead of crashing."""
    for attempt in range(1, 41):
        try:
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(row)
            return
        except PermissionError:
            print(f"  Cannot write to {path}. Close it if it is open in Excel (retry {attempt}/40 in 15s)")
            time.sleep(15)
    sys.exit(f"STOPPED: {path} stayed locked. Close Excel and run the same command again; it will resume.")

def raw_path(out, url):
    return os.path.join(out, "raw", hashlib.md5(url.encode()).hexdigest() + ".html.gz")

# ----------------------------------------------------------------------------- commands

def cmd_probe(a, fx):
    html = fx.get(a.url)
    if not html:
        return print("Nothing fetched.")
    path = urlparse(a.url).path.strip("/")
    is_category = path in [c.strip("/") for c in CATEGORIES.values()]
    if is_category:
        links = find_listing_links(html, a.url, a.link_regex)
        print(f"{len(links)} listing links found. First 10:")
        for l in links[:10]:
            print("  ", l)
        print("\nNow probe one of those links to check the detail parser.")
    else:
        os.makedirs(a.out, exist_ok=True)
        saved = os.path.join(a.out, "probe_" + re.sub(r"\W+", "_", path.split("/")[-1]) + ".html")
        with open(saved, "w", encoding="utf-8") as f:
            f.write(html)
        row = parse_listing(html, a.url, "probe")
        row["image_urls"] = row["image_urls"][:300] + " ..."
        print(json.dumps(row, indent=2, ensure_ascii=False)[:6000])
        print("\nSaved the page HTML to:", saved)

def site_category_paths(fx):
    """Category-style links found on the home page and the houses page: {path: link text}."""
    found = {}
    for page in (BASE, BASE + "/houses-for-sale"):
        html = fx.get(page)
        if not html:
            continue
        for link in BeautifulSoup(html, "lxml").find_all("a", href=True):
            href = urldefrag(urljoin(page, link["href"]))[0]
            p = urlparse(href)
            if p.netloc.replace("www.", "") != urlparse(BASE).netloc.replace("www.", ""):
                continue
            if re.search(r"uploadedfiles|login|register|\.(jpg|png|webp|svg|css|js)$|\d{4,}", p.path, re.I):
                continue
            if re.search(r"for-sale|stands|land|flats|apartments|townhouses|farms|commercial|warehouses|offices|shops|hotels", p.path, re.I):
                found.setdefault(p.path.rstrip("/"), " ".join(link.get_text(" ").split())[:50])
    return found

def cmd_categories(a, fx):
    """Print the category-style links on the site so extra categories can be added."""
    found = site_category_paths(fx)
    for path, text in sorted(found.items()):
        print(f"{path:70s} {text}")
    print(f"\n{len(found)} candidate category links.")

def location_links(html, page_url, root):
    """Links to narrower location pages under a category, e.g. /houses-for-sale/harare-north/highlands."""
    out = []
    for link in BeautifulSoup(html, "lxml").find_all("a", href=True):
        p = urlparse(urldefrag(urljoin(page_url, link["href"]))[0])
        if p.netloc.replace("www.", "") != urlparse(BASE).netloc.replace("www.", ""):
            continue
        path = p.path.rstrip("/")
        if not path.startswith(root + "/") or re.search(r"\d{4,}|showdays|uploadedfiles", path, re.I):
            continue
        if len(path[len(root) + 1:].split("/")) > 2:
            continue
        if path not in out:
            out.append(path)
    return out

def crawl_pages(fx, a, cat, p, seen, csv_path, start=1):
    """Walk ?page=N for one list until it ends. Returns (pages walked, HTML of the first page walked)."""
    misses = empty = walked = 0
    prev, first_html = set(), None
    for page in range(start, a.max_pages + 1):
        html = fx.get(f"{BASE}{p}?page={page}")
        if html is None:
            misses += 1
            print(f"{cat} {p} page {page}: could not fetch ({misses}/3)")
            if misses >= 3:
                break
            continue
        misses = 0
        all_links = find_listing_links(html, BASE + p, a.link_regex)
        if not all_links:
            empty += 1
            print(f"{cat} {p} page {page}: no listing links ({empty}/2)")
            if empty >= 2:
                break
            continue
        empty = 0
        if set(all_links) == prev:
            print(f"{cat} {p} page {page}: same as previous page, end of list")
            break
        prev = set(all_links)
        first_html = first_html or html
        walked += 1
        new = [l for l in all_links if l not in seen]
        print(f"{cat} {p} page {page}: {len(new)} new links ({len(all_links)} on page)")
        for l in new:
            seen.add(l)
            append_csv(csv_path, ["url", "category"], {"url": l, "category": cat})
    return walked, first_html

def cmd_discover(a, fx):
    os.makedirs(a.out, exist_ok=True)
    cats = dict(CATEGORIES)
    for item in a.add_category or []:
        name, _, path = item.partition("=")
        cats[name.strip()] = "/" + path.strip().strip("/")
    new_names = []
    if a.auto_categories:
        have = {c.strip("/") for c in cats.values()}
        for path in site_category_paths(fx):
            top = path.strip("/")
            if "/" in top or "for-sale" not in top or "rent" in top.lower() or "showdays" in top or top in have:
                continue
            name = re.sub(r"[^a-z0-9]+", "-", top.lower()).strip("-")
            cats[name] = "/" + top
            new_names.append(name)
            have.add(top)
        print("New categories to crawl:", ", ".join(f"{k} ({cats[k]})" for k in new_names) or "none found")
    csv_path = os.path.join(a.out, "urls.csv")
    seen = {r["url"] for r in read_csv(csv_path)}
    for cat, p in cats.items():
        if a.category and cat != a.category:
            continue
        if a.auto_categories and not a.category and cat not in new_names:
            continue
        if not a.by_location:
            crawl_pages(fx, a, cat, p, seen, csv_path, a.start_page)
            continue
        # The site only serves ~36 pages per list, so a long list is split into its location pages.
        queue, visited = [p], set()
        while queue and len(visited) < a.max_locations:
            path = queue.pop(0)
            if path in visited:
                continue
            visited.add(path)
            walked, html = crawl_pages(fx, a, cat, path, seen, csv_path)
            print(f"[{cat}] {path}: {walked} pages | total URLs so far: {len(seen)}")
            if html and walked >= a.split_at:
                queue.extend(c for c in location_links(html, BASE + path, p) if c not in visited)
    print("Total URLs:", len(seen))

def cmd_details(a, fx):
    os.makedirs(os.path.join(a.out, "raw"), exist_ok=True)
    out_csv = os.path.join(a.out, "listings.csv")
    done = {r["listing_url"] for r in read_csv(out_csv)}
    todo = [r for r in read_csv(os.path.join(a.out, "urls.csv"))
            if r["url"] not in done and (not a.category or r["category"] == a.category)]
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(todo)} listings to scrape")
    for i, r in enumerate(todo, 1):
        html = fx.get(r["url"])
        if not html:
            continue
        with gzip.open(raw_path(a.out, r["url"]), "wt", encoding="utf-8") as f:
            f.write(html)
        append_csv(out_csv, COLUMNS, parse_listing(html, r["url"], r["category"]))
        if i % 25 == 0:
            print(f"  {i}/{len(todo)}")
    now_done = {r["listing_url"] for r in read_csv(out_csv)}
    left = [r for r in read_csv(os.path.join(a.out, "urls.csv"))
            if r["url"] not in now_done and (not a.category or r["category"] == a.category)]
    print(f"Finished this run. Scraped so far: {len(now_done)}. Still missing"
          f"{' in ' + a.category if a.category else ''}: {len(left)}"
          + (" - run the same command again to retry them." if left else "."))

def cmd_reparse(a, fx):
    out_csv = os.path.join(a.out, "listings.csv")
    if os.path.exists(out_csv):
        os.replace(out_csv, out_csv + ".bak")
    for r in read_csv(os.path.join(a.out, "urls.csv")):
        p = raw_path(a.out, r["url"])
        if os.path.exists(p):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                append_csv(out_csv, COLUMNS, parse_listing(f.read(), r["url"], r["category"]))
    print("Rebuilt", out_csv)

def cmd_images(a, fx):
    """Download up to --max-images photos per listing into images/<listing_id>/ and log them in image_index.csv."""
    global LIVE_LINE
    idx = os.path.join(a.out, "image_index.csv")
    index_rows = read_csv(idx)
    done = {(r["listing_id"], r["image_url"]) for r in index_rows}   # photos already saved for that listing
    by_url = {r["image_url"]: r["path"] for r in index_rows}        # lets duplicate listings reuse a file
    miss_path = os.path.join(a.out, "image_missing.csv")           # photos the site no longer has (404)
    missing = {(r["listing_id"], r["image_url"]) for r in read_csv(miss_path)}
    skip = set(a.exclude_category or [])
    rows = [r for r in read_csv(os.path.join(a.out, "listings.csv"))
            if (not a.category or r["category"] == a.category) and r["category"] not in skip]
    if a.limit:
        rows = rows[: a.limit]

    def urls_of(r):
        return [u for u in (r["image_urls"] or "").split("|") if u][: a.max_images]

    todo_total = sum(1 for r in rows for u in urls_of(r) if (r["listing_id"], u) not in done and (r["listing_id"], u) not in missing)
    print(f"{len(rows)} listings to check, up to {a.max_images} photos each; {len(done)} photos already saved; "
          f"{todo_total} photos still to fetch")
    got = failed = gone = processed = total_bytes = 0
    last_kb = last_s = 0.0
    t0 = time.time()
    LIVE_LINE = True

    def status(i, r, n, nurls):
        el = max(time.time() - t0, 1e-6)
        rate = processed / el
        eta = (todo_total - processed) / rate / 3600 if processed else 0
        line = (f"[{i}/{len(rows)}] {r['listing_id']} photo {n + 1}/{nurls} | last {last_kb:.0f} KB in {last_s:.1f}s | "
                f"avg {total_bytes / 1024 / el:.0f} KB/s | {rate * 60:.0f} photos/min | {got} saved, "
                f"{total_bytes / 1e6:.0f} MB | ETA {eta:.1f} h")
        sys.stdout.write("\r" + line[:124].ljust(124))
        sys.stdout.flush()

    for i, r in enumerate(rows, 1):
        urls = urls_of(r)
        for n, u in enumerate(urls):
            if (r["listing_id"], u) in done or (r["listing_id"], u) in missing:
                continue
            processed += 1
            ext = os.path.splitext(urlparse(u).path)[1].lower() or ".webp"
            folder = os.path.join(a.out, "images", r["listing_id"])
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{n}{ext}")
            if u in by_url and os.path.exists(by_url[u]):      # same photo used by another listing: copy, don't re-download
                shutil.copyfile(by_url[u], path)
                append_csv(idx, ["listing_id", "image_url", "path"], {"listing_id": r["listing_id"], "image_url": u, "path": path})
                done.add((r["listing_id"], u))
                status(i, r, n, len(urls))
                continue
            t1 = time.time()
            # try the full-size original first, then a thumbnail if the original is missing
            data = fx.get(u, binary=True, delay=a.image_delay) or \
                   fx.get(re.sub(r"(\.\w+)$", r"_thumbnail695\1", u), binary=True, delay=a.image_delay)
            if not data:
                if fx.last_status == 404:      # gone from the site for good: log it and never retry
                    append_csv(miss_path, ["listing_id", "image_url"], {"listing_id": r["listing_id"], "image_url": u})
                    missing.add((r["listing_id"], u))
                    gone += 1
                else:
                    failed += 1
                status(i, r, n, len(urls))
                continue
            with open(path, "wb") as f:
                f.write(data)
            append_csv(idx, ["listing_id", "image_url", "path"], {"listing_id": r["listing_id"], "image_url": u, "path": path})
            done.add((r["listing_id"], u))
            by_url[u] = path
            got += 1
            total_bytes += len(data)
            last_kb, last_s = len(data) / 1024, time.time() - t1
            status(i, r, n, len(urls))
        if i % 50 == 0:
            say(f"  {i}/{len(rows)} listings | {got} photos this run | {total_bytes / 1e6:.0f} MB | {gone} gone (404) | {failed} failed")
    LIVE_LINE = False
    print()
    avg = total_bytes / got / 1024 if got else 0
    print(f"Finished this run: {got} photos downloaded ({total_bytes / 1e6:.0f} MB, average {avg:.0f} KB), "
          f"{gone} no longer on the site (404, skipped for good), {failed} failed."
          + (" Run the same command again to retry the failed ones." if failed else ""))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["probe", "categories", "discover", "details", "images", "reparse"])
    ap.add_argument("url", nargs="?", help="page to test (probe only)")
    ap.add_argument("--contact", default="student@example.com", help="your email, shown in the User-Agent")
    ap.add_argument("--out", default="zim_property_data")
    ap.add_argument("--delay", type=float, default=4.0, help="seconds between page requests (randomised)")
    ap.add_argument("--image-delay", type=float, default=1.0)
    ap.add_argument("--max-pages", type=int, default=400)
    ap.add_argument("--auto-categories", action="store_true", help="discover: also crawl every for-sale category found in the site menu (no rentals)")
    ap.add_argument("--by-location", action="store_true", help="discover: split long lists into the site's location pages")
    ap.add_argument("--split-at", type=int, default=30, help="split a list into locations when it has at least this many pages")
    ap.add_argument("--max-locations", type=int, default=300)
    ap.add_argument("--start-page", type=int, default=1, help="first page number (discover), to resume part-way")
    ap.add_argument("--max-images", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="only scrape N listings (testing)")
    ap.add_argument("--category", help="only this category name (discover, details, images)")
    ap.add_argument("--exclude-category", action="append", help="images: skip this category (repeatable)")
    ap.add_argument("--add-category", action="append", metavar="NAME=/path", help="extra category, e.g. farm=/farms-for-sale (repeatable)")
    ap.add_argument("--link-regex", default=DEFAULT_LINK_REGEX)
    a = ap.parse_args()
    if a.command == "probe" and not a.url:
        ap.error("probe needs a URL")
    fx = Fetcher(a.contact, a.delay) if a.command != "reparse" else None
    try:
        {"probe": cmd_probe, "categories": cmd_categories, "discover": cmd_discover, "details": cmd_details,
         "images": cmd_images, "reparse": cmd_reparse}[a.command](a, fx)
    except Blocked as e:
        sys.exit(f"STOPPED: {e}")
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to resume.")

if __name__ == "__main__":
    main()
