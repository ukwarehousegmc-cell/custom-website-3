"""
Scraper module — extracts products from website collection pages.
Uses Shopify JSON API when available, falls back to HTML scraping.
"""

import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,en-US;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def get_soup(url, session=None):
    """Fetch URL and return BeautifulSoup object."""
    s = session or requests.Session()
    resp = s.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml"), s


# ─── Shopify JSON API approach (preferred) ───

def try_shopify_json(collection_url, session=None):
    """
    Try to get products via Shopify's /products.json endpoint.
    Returns list of product dicts or None if not a Shopify store.
    """
    s = session or requests.Session()
    parsed = urlparse(collection_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    
    # Try /collections/xxx/products.json
    json_url = f"{base}{path}/products.json?limit=250"
    
    try:
        resp = s.get(json_url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if "products" in data:
                return data["products"], s
    except Exception:
        pass
    
    return None, s


def scrape_shopify_product(product_json, base_url, collection_name, website_name):
    """Convert Shopify JSON product data into our standard format."""
    data = {
        "url": f"{base_url}/products/{product_json['handle']}",
        "title": product_json.get("title", ""),
        "description": "",
        "prices": [],
        "images": [],
        "tables": [],
        "variants": [],
        "breadcrumbs": [],
        "full_text": "",
    }
    
    # Description (HTML)
    body_html = product_json.get("body_html", "") or ""
    if body_html:
        soup = BeautifulSoup(body_html, "lxml")
        data["description"] = soup.get_text(separator="\n", strip=True)
        
        # Extract tables from description
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                data["tables"].append(rows)
        
        # Extract product-specs section
        product_specs = soup.find(class_="product-specs")
        if product_specs:
            specs_rows = []
            for tr in product_specs.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    specs_rows.append(cells)
            if specs_rows:
                data["product_specs"] = specs_rows
            else:
                # Try dl/dt/dd or div-based specs
                specs_text = product_specs.get_text(separator="\n", strip=True)
                if specs_text:
                    data["product_specs_text"] = specs_text
        
        data["full_text"] = data["description"]
    
    # Images
    for img in product_json.get("images", []):
        src = img.get("src", "")
        if src:
            data["images"].append(src)
    
    # Prices
    for variant in product_json.get("variants", []):
        price = variant.get("price")
        if price:
            data["prices"].append(f"£{price}")
    data["prices"] = list(set(data["prices"]))
    
    # Variants — extract option names and values
    options = product_json.get("options", [])
    for opt in options:
        opt_name = opt.get("name", "")
        opt_values = opt.get("values", [])
        if opt_values and not (len(opt_values) == 1 and opt_values[0].lower() in ["default title", "default"]):
            data["variants"].append({
                "label": opt_name,
                "options": opt_values,
            })
    
    # Also store raw variant data for AI to use
    raw_variants = []
    for v in product_json.get("variants", []):
        rv = {
            "title": v.get("title", ""),
            "price": v.get("price", ""),
            "sku": v.get("sku", ""),
            "option1": v.get("option1"),
            "option2": v.get("option2"),
            "option3": v.get("option3"),
        }
        raw_variants.append(rv)
    data["raw_variants"] = raw_variants
    
    # Product type & tags from JSON
    data["product_type"] = product_json.get("product_type", "")
    data["vendor"] = product_json.get("vendor", "")
    data["tags"] = product_json.get("tags", [])
    if isinstance(data["tags"], str):
        data["tags"] = [t.strip() for t in data["tags"].split(",")]
    
    # If no product_specs found in body_html, try scraping the live page
    if not data.get("product_specs") and not data.get("product_specs_text"):
        try:
            live_url = f"{base_url}/products/{product_json['handle']}"
            resp = requests.get(live_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                live_soup = BeautifulSoup(resp.text, "lxml")
                ps = live_soup.find(class_="product-specs")
                if ps:
                    specs_rows = []
                    for tr in ps.find_all("tr"):
                        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                        if cells:
                            specs_rows.append(cells)
                    if specs_rows:
                        data["product_specs"] = specs_rows
                    else:
                        specs_text = ps.get_text(separator="\n", strip=True)
                        if specs_text:
                            data["product_specs_text"] = specs_text
        except Exception:
            pass
    
    return data


# ─── HTML scraping fallback ───

def extract_product_links(soup, base_url):
    """Extract product links ONLY from the main product grid/listing.
    
    Strategy:
    1. First try WooCommerce li.product containers (most reliable)
    2. Then try common product grid containers (ul.products, .product-list, etc.)
    3. Then try Magento product-item containers
    4. Fallback: scan all links but EXCLUDE header, nav, footer, sidebar, dropdowns
    """
    links = []
    seen = set()

    def add_link(href):
        full = urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            links.append(full)

    # ── Strategy 1: WooCommerce li.product (most reliable) ──
    woo_products = soup.select("ul.products li.product a[href]")
    if not woo_products:
        # Also try without ul.products wrapper
        woo_products = soup.select("li.product a[href]")
    
    if woo_products:
        for a in woo_products:
            href = a["href"]
            if any(p in href.lower() for p in ["/product/", "/products/", "/p/"]):
                add_link(href)
        if links:
            return links

    # ── Strategy 2: Common product grid containers ──
    grid_selectors = [
        ".products-grid a[href]",
        ".product-list a[href]",
        ".product-grid a[href]",
        "[data-product] a[href]",
        ".collection-products a[href]",
    ]
    for sel in grid_selectors:
        grid_links = soup.select(sel)
        for a in grid_links:
            href = a["href"]
            if any(p in href.lower() for p in ["/product/", "/products/", "/p/", "/-p-", "/item/"]):
                add_link(href)
        if links:
            return links

    # ── Strategy 3: Magento product-item containers ──
    for container in soup.find_all(class_=lambda c: c and any("product-item" in x.lower() for x in (c if isinstance(c, list) else [c]))):
        for a in container.find_all("a", href=True):
            href = a["href"]
            parsed_href = urlparse(urljoin(base_url, href))
            if parsed_href.netloc == urlparse(base_url).netloc and parsed_href.path not in ['/', '']:
                add_link(href)
    if links:
        return links

    # ── Strategy 4: Fallback — scan all links but strip nav/header/footer/sidebar/dropdowns ──
    # Remove sections that are NOT the main content
    exclude_tags = re.compile(
        r"header|nav|footer|sidebar|menu|dropdown|breadcrumb|recent|recommend|related|"
        r"also.like|you.may|featured|trending|best.sell|popular|cross.sell|upsell|viewed|suggested",
        re.I
    )

    # Clone soup so we don't destroy the original
    from copy import copy
    work_soup = BeautifulSoup(str(soup), "lxml")

    for el in work_soup.find_all(["header", "nav", "footer", "aside"]):
        el.decompose()

    for el in work_soup.find_all(["section", "div"], class_=True):
        classes = " ".join(el.get("class") or [])
        el_id = el.get("id") or ""
        if exclude_tags.search(classes) or exclude_tags.search(el_id):
            try:
                el.decompose()
            except Exception:
                pass

    for a in work_soup.find_all("a", href=True):
        href = a["href"]
        if any(p in href.lower() for p in ["/product/", "/products/", "/p/", "/-p-", "/item/"]):
            add_link(href)

    return links


def find_next_page(soup, base_url):
    """Find next page URL if pagination exists."""
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        classes = " ".join(a.get("class", [])).lower()
        if "next" in text or "next" in classes or "›" in text or "»" in text:
            return urljoin(base_url, a["href"])
    
    link = soup.find("a", rel="next")
    if link and link.get("href"):
        return urljoin(base_url, link["href"])
    
    return None


def scrape_product_page(url, session=None):
    """Scrape a single product page via HTML and extract all available data."""
    s = session or requests.Session()
    
    # First try Shopify product JSON
    parsed = urlparse(url)
    json_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}.json"
    
    try:
        resp = s.get(json_url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            pdata = resp.json().get("product")
            if pdata:
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                result = scrape_shopify_product(pdata, base_url, "", "")
                return result, s
    except Exception:
        pass
    
    # Fallback to HTML scraping
    soup, s = get_soup(url, s)
    data = {"url": url}
    
    # Title
    h1 = soup.find("h1")
    data["title"] = h1.get_text(strip=True) if h1 else ""
    
    # Price(s) — prefer "Regular price" over "Member price" / discounted price
    prices = []
    # Strategy 1: Look for "Regular price" label near a text-lg element
    for text_lg in soup.find_all(class_="text-lg"):
        parent = text_lg.parent
        if parent:
            parent_text = parent.get_text(strip=True).lower()
            if "regular" in parent_text:
                found = re.findall(r"[\d,]+\.?\d*", text_lg.get_text(strip=True))
                if found:
                    prices.append(f"£{found[0]}")
                    break
    # Strategy 2: Look for any container with "Regular price" text and extract £ amount
    if not prices:
        for el in soup.find_all(string=re.compile(r"Regular\s+price", re.I)):
            container = el.parent
            if container:
                # Check siblings/parent for price
                parent = container.parent
                if parent:
                    found = re.findall(r"[\d,]+\.?\d*\s*£|£\s*[\d,]+\.?\d*|[\d,]+\.?\d*\s*£\s*incl", parent.get_text())
                    if not found:
                        found = re.findall(r"([\d,]+\.?\d*)\s*£", parent.get_text())
                    if found:
                        price_str = re.sub(r"[^\d.]", "", found[0])
                        if price_str:
                            prices.append(f"£{price_str}")
                            break
    # Strategy 3: Fallback to text-lg (first one with a price)
    if not prices:
        for text_lg in soup.find_all(class_="text-lg"):
            text = text_lg.get_text(strip=True)
            found = re.findall(r"£[\d,]+\.?\d*", text)
            if not found:
                found = re.findall(r"([\d,]+\.?\d*)\s*£", text)
                found = [f"£{f}" for f in found]
            if found:
                prices.extend(found)
                break
    # Strategy 4: Fallback to price classes
    if not prices:
        for el in soup.find_all(class_=re.compile(r"price", re.I)):
            text = el.get_text(strip=True)
            found = re.findall(r"£[\d,]+\.?\d*", text)
            prices.extend(found)
    meta_price = soup.find("meta", {"property": "product:price:amount"})
    if meta_price:
        prices.append(f"£{meta_price['content']}")
    data["prices"] = list(set(prices))
    
    # Images
    images = []
    for img in soup.find_all("img", src=True):
        src = urljoin(url, img["src"])
        if any(p in src.lower() for p in ["product", "upload", "media", "image"]):
            images.append(src)
    data["images"] = list(set(images))
    
    # Description
    desc_candidates = soup.find_all(class_=re.compile(r"desc|detail|info|content|tab-pane|product-body", re.I))
    descriptions = []
    for d in desc_candidates:
        text = d.get_text(separator="\n", strip=True)
        if len(text) > 50:
            descriptions.append(text)
    data["description"] = "\n\n".join(descriptions) if descriptions else ""
    
    # Tables
    tables = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    data["tables"] = tables
    
    # Variants
    variants = []
    for select in soup.find_all("select"):
        label = ""
        sel_id = select.get("id", "")
        sel_name = select.get("name", "")
        if sel_id:
            lbl = soup.find("label", {"for": sel_id})
            if lbl:
                label = lbl.get_text(strip=True)
        if not label:
            label = sel_name
        options = []
        for opt in select.find_all("option"):
            val = opt.get_text(strip=True)
            if val and val.lower() not in ["select", "choose", "please select", "--"]:
                options.append(val)
        if options:
            variants.append({"label": label, "options": options})
    data["variants"] = variants
    
    # Product specs (class="product-specs")
    product_specs = soup.find(class_="product-specs")
    if product_specs:
        specs_rows = []
        for tr in product_specs.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if cells:
                specs_rows.append(cells)
        if specs_rows:
            data["product_specs"] = specs_rows
        else:
            specs_text = product_specs.get_text(separator="\n", strip=True)
            if specs_text:
                data["product_specs_text"] = specs_text
    
    # Breadcrumbs
    breadcrumbs = []
    for nav in soup.find_all(class_=re.compile(r"breadcrumb", re.I)):
        for a in nav.find_all("a"):
            breadcrumbs.append(a.get_text(strip=True))
    data["breadcrumbs"] = breadcrumbs
    
    # ── Magento Bundle Options (custom properties) ──
    bundle_options = []
    page_text = str(soup)
    
    # Extract optionConfig JSON from Magento bundle products using brace-counting
    option_config = None
    oc_start = page_text.find('"optionConfig":')
    if oc_start == -1:
        oc_start = page_text.find('"optionConfig" :')
    if oc_start >= 0:
        brace_start = page_text.find('{', oc_start)
        if brace_start >= 0:
            depth = 0
            i = brace_start
            while i < len(page_text):
                if page_text[i] == '{':
                    depth += 1
                elif page_text[i] == '}':
                    depth -= 1
                if depth == 0:
                    try:
                        option_config = json.loads(page_text[brace_start:i+1])
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
                i += 1

    if option_config:
        try:
            positions = option_config.get("positions", [])
            base_prices = option_config.get("prices", {})
            base_price = base_prices.get("finalPrice", {}).get("amount", 0)
            
            for pos in positions:
                opt_data = option_config.get("options", {}).get(str(pos), {})
                if not opt_data:
                    continue
                
                title = opt_data.get("title", "")
                selections = opt_data.get("selections", {})
                
                option_items = []
                for sel_id, sel_data in selections.items():
                    price_amount = sel_data.get("prices", {}).get("finalPrice", {}).get("amount", 0)
                    if isinstance(price_amount, str):
                        price_amount = float(price_amount) if price_amount else 0
                    
                    option_items.append({
                        "id": sel_id,
                        "name": sel_data.get("name", ""),
                        "price_adjustment": float(price_amount),
                    })
                
                # Detect if this is a colour option (thumbnails with images)
                is_colour = "colour" in title.lower() or "color" in title.lower()
                
                # Try to extract colour swatches/thumbnails
                colour_images = {}
                if is_colour:
                    for li in soup.find_all("li", id=re.compile(r"li-\d+")):
                        li_id = li.get("id", "").replace("li-", "")
                        img = li.find("img")
                        if img and img.get("src"):
                            colour_images[li_id] = urljoin(url, img["src"])
                
                bundle_options.append({
                    "title": title,
                    "required": True,
                    "type": "colour_swatch" if is_colour else "dropdown",
                    "items": option_items,
                    "colour_images": colour_images if colour_images else None,
                })
            
            if bundle_options:
                data["bundle_options"] = bundle_options
                data["base_price"] = float(base_price)
                data["is_bundle"] = True
                
        except (KeyError, ValueError):
            pass
    
    # Full text
    body = soup.find("body")
    data["full_text"] = body.get_text(separator="\n", strip=True)[:15000] if body else ""
    
    return data, s


# ─── Main scrape function ───

def try_magento_graphql(base_url, url_path, progress_callback=None):
    """Try to scrape products via Magento 2 GraphQL API."""
    session = requests.Session()
    graphql_url = f"{base_url}/graphql"
    
    if progress_callback:
        progress_callback(f"🔌 Trying Magento GraphQL API...")
    
    query = """
    query($urlPath: String!, $page: Int!, $pageSize: Int!) {
      categoryList(filters: { url_path: { eq: $urlPath } }) {
        id name url_path product_count
        products(pageSize: $pageSize, currentPage: $page, sort: { position: ASC }) {
          items {
            name sku url_key __typename
            price_range {
              minimum_price {
                regular_price { value currency }
                final_price { value currency }
                discount { amount_off percent_off }
              }
            }
            description { html }
            short_description { html }
            small_image { url label }
            media_gallery { url label }
            ... on BundleProduct {
              items {
                title required
                options { label price quantity }
              }
              dynamic_price
            }
            ... on ConfigurableProduct {
              configurable_options {
                label attribute_code
                values { label swatch_data { value } }
              }
            }
          }
          total_count
          page_info { current_page page_size total_pages }
        }
      }
    }
    """
    
    try:
        all_products = []
        page = 1
        page_size = 50
        
        while True:
            resp = session.post(
                graphql_url,
                headers={**HEADERS, "Content-Type": "application/json"},
                json={"query": query, "variables": {"urlPath": url_path, "page": page, "pageSize": page_size}},
                timeout=30,
            )
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            categories = data.get("data", {}).get("categoryList", [])
            if not categories:
                return None
            
            cat = categories[0]
            products = cat.get("products", {})
            items = products.get("items", [])
            total = products.get("total_count", 0)
            
            if not items:
                if page == 1:
                    return None
                break
            
            all_products.extend(items)
            
            if progress_callback:
                progress_callback(f"📦 GraphQL page {page}: {len(items)} products (total: {len(all_products)}/{total})")
            
            page_info = products.get("page_info", {})
            if page >= page_info.get("total_pages", 1):
                break
            
            page += 1
            time.sleep(0.5)
        
        if not all_products:
            return None
        
        if progress_callback:
            progress_callback(f"✅ Magento GraphQL: Found {len(all_products)} products in '{cat['name']}'")
        
        # Convert to standard format
        website_name = urlparse(base_url).netloc.replace("www.", "")
        converted = []
        for p in all_products:
            price_data = p.get("price_range", {}).get("minimum_price", {})
            final_price = price_data.get("final_price", {}).get("value", 0)
            regular_price = price_data.get("regular_price", {}).get("value", 0)
            currency = price_data.get("final_price", {}).get("currency", "GBP")
            
            product = {
                "title": p["name"],
                "url": f"{base_url}/{p['url_key']}.html",
                "prices": [f"£{final_price:.2f}"],
                "description": p.get("description", {}).get("html", "") or p.get("short_description", {}).get("html", ""),
                "images": [img["url"] for img in p.get("media_gallery", []) if img.get("url")],
                "variants": [],
                "tables": [],
                "breadcrumbs": [cat["name"]],
            }
            
            if not product["images"] and p.get("small_image", {}).get("url"):
                product["images"] = [p["small_image"]["url"]]
            
            # Configurable options → variants
            if p.get("configurable_options"):
                for opt in p["configurable_options"]:
                    product["variants"].append({
                        "label": opt["label"],
                        "options": [v["label"] for v in opt.get("values", [])]
                    })
            
            # Bundle options → bundle_options
            if p.get("items"):  # Bundle product
                bundle_opts = []
                for bi in p["items"]:
                    bundle_opts.append({
                        "title": bi["title"],
                        "required": bi.get("required", True),
                        "type": "colour_swatch" if "colour" in bi["title"].lower() or "color" in bi["title"].lower() else "dropdown",
                        "items": [{"name": opt["label"], "price_adjustment": float(opt.get("price", 0) or 0)} for opt in bi.get("options", [])],
                    })
                if bundle_opts:
                    product["bundle_options"] = bundle_opts
                    product["is_bundle"] = True
                    product["base_price"] = final_price
            
            # Price comparison
            if regular_price > final_price:
                product["prices"].append(f"£{regular_price:.2f}")
            
            converted.append(product)
        
        return {
            "collection_url": f"{base_url}/{url_path}.html",
            "collection_name": cat["name"],
            "website_name": website_name,
            "total_products": len(converted),
            "products": converted,
        }
    
    except Exception as e:
        if progress_callback:
            progress_callback(f"⚠️ GraphQL error: {e}")
        return None


def try_algolia_search(base_url, collection_url, collection_name, progress_callback=None):
    """Try to scrape products via Algolia search API (used by Magento 2 Hyva frontends)."""
    session = requests.Session()
    
    if progress_callback:
        progress_callback("🔍 Checking for Algolia search API...")
    
    try:
        # Load the page to get Algolia config
        resp = session.get(collection_url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            return None
        
        html = resp.text
        
        # Extract Algolia config
        app_id_match = re.search(r'applicationId":"([^"]+)', html)
        api_key_match = re.search(r'apiKey":"([^"]+)', html)
        
        if not app_id_match or not api_key_match:
            return None
        
        app_id = app_id_match.group(1)
        api_key = api_key_match.group(1)
        
        # Find product index name (look for _products_ indices)
        indices = re.findall(r'([a-z0-9_]+_products_[a-z_]+)', html)
        if not indices:
            # Fallback: try base index + _products suffix
            base_idx = re.findall(r'indexName":"([^"]+)', html)
            if base_idx:
                indices = [base_idx[0] + "_products_created_at_desc", base_idx[0]]
        
        if not indices:
            return None
        
        index_name = indices[0]
        
        if progress_callback:
            progress_callback(f"🔌 Found Algolia: {app_id} / {index_name}")
        
        # Search using the collection name as query
        search_term = collection_name.replace("-", " ").replace(".html", "").strip()
        
        all_products = []
        page = 0
        hits_per_page = 50
        
        while True:
            resp = session.post(
                f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query",
                headers={
                    "X-Algolia-Application-Id": app_id,
                    "X-Algolia-API-Key": api_key,
                    "Content-Type": "application/json",
                },
                json={"params": f"query={search_term}&hitsPerPage={hits_per_page}&page={page}"},
                timeout=30,
            )
            
            if resp.status_code != 200:
                break
            
            data = resp.json()
            hits = data.get("hits", [])
            total = data.get("nbHits", 0)
            
            if not hits:
                break
            
            all_products.extend(hits)
            
            if progress_callback:
                progress_callback(f"📦 Algolia page {page + 1}: {len(hits)} products (total: {len(all_products)}/{total})")
            
            if len(all_products) >= total or len(hits) < hits_per_page:
                break
            
            page += 1
            time.sleep(0.3)
        
        if not all_products:
            return None
        
        if progress_callback:
            progress_callback(f"✅ Algolia: Found {len(all_products)} products")
        
        # Convert to standard format
        website_name = urlparse(base_url).netloc.replace("www.", "")
        converted = []
        for p in all_products:
            price_data = p.get("price", {}).get("GBP", {})
            price = price_data.get("default", 0) if isinstance(price_data, dict) else 0
            original = price_data.get("default_original_formated", "") if isinstance(price_data, dict) else ""
            
            product = {
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "prices": [f"£{price:.2f}"] if price else [],
                "description": p.get("description", "") or p.get("short_description", ""),
                "images": [],
                "variants": [],
                "tables": [],
                "breadcrumbs": [],
            }
            
            # Images
            if p.get("image_url"):
                product["images"].append(p["image_url"])
            if p.get("thumbnail_url"):
                product["images"].append(p["thumbnail_url"])
            if p.get("media_gallery"):
                for img in p.get("media_gallery", []):
                    if isinstance(img, dict) and img.get("url"):
                        product["images"].append(img["url"])
                    elif isinstance(img, str):
                        product["images"].append(img)
            
            # Categories
            if p.get("categories"):
                if isinstance(p["categories"], dict):
                    for cat in p["categories"].values():
                        if isinstance(cat, str):
                            product["breadcrumbs"].append(cat)
            
            converted.append(product)
        
        return {
            "collection_url": collection_url,
            "collection_name": collection_name,
            "website_name": website_name,
            "total_products": len(converted),
            "products": converted,
        }
    
    except Exception as e:
        if progress_callback:
            progress_callback(f"⚠️ Algolia error: {e}")
        return None


def scrape_collection(collection_url, progress_callback=None):
    """Scrape all products from a collection URL. Returns list of product data dicts."""
    session = requests.Session()
    parsed = urlparse(collection_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    
    # Extract collection name from URL
    path = parsed.path.strip("/")
    collection_name = path.split("/")[-1].replace("-", " ").title()
    website_name = parsed.netloc.replace("www.", "")
    
    # ── Try Algolia Search API (Magento 2 Hyva/React frontends) ──
    algolia_result = try_algolia_search(base_url, collection_url, collection_name, progress_callback)
    if algolia_result and algolia_result.get("products"):
        return algolia_result
    
    # ── Try Magento GraphQL ──
    url_path = path.split(".")[0]  # Remove .html extension
    graphql_result = try_magento_graphql(base_url, url_path, progress_callback)
    if graphql_result and graphql_result.get("products"):
        return graphql_result
    
    # ── Try Shopify JSON API ──
    if progress_callback:
        progress_callback("🔍 Trying Shopify JSON API...")
    
    shopify_products, session = try_shopify_json(collection_url, session)
    
    if shopify_products is not None:
        if progress_callback:
            progress_callback(f"✅ Shopify API found! {len(shopify_products)} products in collection")
        
        products = []
        for i, sp in enumerate(shopify_products):
            if progress_callback:
                progress_callback(f"📦 Processing {i+1}/{len(shopify_products)}: {sp.get('title', 'Unknown')}")
            
            product_data = scrape_shopify_product(sp, base_url, collection_name, website_name)
            products.append(product_data)
        
        return {
            "collection_url": collection_url,
            "collection_name": collection_name,
            "website_name": website_name,
            "total_products": len(products),
            "products": products,
        }
    
    # ── Try Sitemap for this collection ──
    if progress_callback:
        progress_callback("📍 Trying sitemap to find products...")
    
    sitemap_products = []
    collection_path = parsed.path.strip("/").split(".")[0]  # e.g. "boot-wipers"
    
    for sitemap_path in ["/sitemap.xml", "/pub/sitemap.xml", "/sitemap_products_1.xml"]:
        try:
            resp = session.get(f"{base_url}{sitemap_path}", headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            
            sitemap_soup = BeautifulSoup(resp.text, "lxml-xml")
            
            # Check for sitemap index
            sub_sitemaps = sitemap_soup.find_all("sitemap")
            if sub_sitemaps:
                for sm in sub_sitemaps:
                    loc = sm.find("loc")
                    if loc:
                        try:
                            sr = session.get(loc.text.strip(), headers=HEADERS, timeout=15)
                            if sr.status_code == 200:
                                sub_soup = BeautifulSoup(sr.text, "lxml-xml")
                                for url_tag in sub_soup.find_all("url"):
                                    loc_tag = url_tag.find("loc")
                                    if not loc_tag:
                                        continue
                                    url = loc_tag.text.strip()
                                    has_image = url_tag.find("image:image") is not None
                                    # Match products under this collection path
                                    if has_image and collection_path in url:
                                        sitemap_products.append(url)
                        except Exception:
                            pass
                continue
            
            # Regular sitemap — find product URLs matching this collection
            for url_tag in sitemap_soup.find_all("url"):
                loc_tag = url_tag.find("loc")
                if not loc_tag:
                    continue
                url = loc_tag.text.strip()
                has_image = url_tag.find("image:image") is not None
                
                if has_image and collection_path in url:
                    sitemap_products.append(url)
            
            if sitemap_products:
                break
        except Exception:
            pass
    
    if sitemap_products:
        if progress_callback:
            progress_callback(f"✅ Sitemap: Found {len(sitemap_products)} products for '{collection_name}'")
        
        products = []
        for i, link in enumerate(sitemap_products):
            if progress_callback:
                progress_callback(f"Scraping product {i+1}/{len(sitemap_products)}: {link}")
            try:
                product_data, session = scrape_product_page(link, session)
                products.append(product_data)
                time.sleep(0.5)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error scraping {link}: {e}")
                products.append({"url": link, "error": str(e)})
        
        return {
            "collection_url": collection_url,
            "collection_name": collection_name,
            "website_name": website_name,
            "total_products": len(products),
            "products": products,
        }
    
    # ── Fallback to HTML scraping ──
    if progress_callback:
        progress_callback("⚠️ Sitemap didn't match. Using HTML scraping...")
    
    all_product_links = []
    page_url = collection_url
    page_num = 1
    
    while page_url:
        if progress_callback:
            progress_callback(f"Scanning page {page_num}: {page_url}")
        
        soup, session = get_soup(page_url, session)
        links = extract_product_links(soup, page_url)
        
        new_links = [l for l in links if l not in all_product_links]
        all_product_links.extend(new_links)
        
        if progress_callback:
            progress_callback(f"Found {len(new_links)} products on page {page_num} (total: {len(all_product_links)})")
        
        next_page = find_next_page(soup, page_url)
        if next_page and next_page != page_url:
            page_url = next_page
            page_num += 1
            time.sleep(1)
        else:
            break
    
    # Scrape each product page
    products = []
    for i, link in enumerate(all_product_links):
        if progress_callback:
            progress_callback(f"Scraping product {i+1}/{len(all_product_links)}: {link}")
        
        try:
            product_data, session = scrape_product_page(link, session)
            products.append(product_data)
            time.sleep(0.5)
        except Exception as e:
            if progress_callback:
                progress_callback(f"Error scraping {link}: {e}")
            products.append({"url": link, "error": str(e)})
    
    return {
        "collection_url": collection_url,
        "collection_name": collection_name,
        "website_name": website_name,
        "total_products": len(products),
        "products": products,
    }


def scrape_full_site(site_url, progress_callback=None):
    """
    Scrape ALL products from a website (not just one collection).
    Works for Shopify stores via /products.json and sitemap.
    Falls back to crawling collection pages for non-Shopify sites.
    """
    session = requests.Session()
    parsed = urlparse(site_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    website_name = parsed.netloc.replace("www.", "")

    if progress_callback:
        progress_callback(f"🌐 Starting full site scrape: {website_name}")

    # ── Try Shopify /products.json (paginated) ──
    all_products = []
    page = 1
    is_shopify = False

    try:
        while True:
            json_url = f"{base_url}/products.json?limit=250&page={page}"
            if progress_callback:
                progress_callback(f"🔍 Trying Shopify API page {page}...")

            resp = session.get(json_url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                break

            data = resp.json()
            products = data.get("products", [])
            if not products:
                break

            is_shopify = True
            all_products.extend(products)

            if progress_callback:
                progress_callback(f"✅ Page {page}: found {len(products)} products (total: {len(all_products)})")

            if len(products) < 250:
                break

            page += 1
            time.sleep(1)
    except Exception as e:
        if progress_callback:
            progress_callback(f"⚠️ Shopify API error: {e}")

    if is_shopify and all_products:
        if progress_callback:
            progress_callback(f"🎯 Shopify store detected! Total products: {len(all_products)}")

        products = []
        for i, sp in enumerate(all_products):
            if progress_callback:
                progress_callback(f"📦 Processing {i+1}/{len(all_products)}: {sp.get('title', 'Unknown')}")
            product_data = scrape_shopify_product(sp, base_url, "All Products", website_name)
            products.append(product_data)

        return {
            "collection_url": site_url,
            "collection_name": "All Products",
            "website_name": website_name,
            "total_products": len(products),
            "products": products,
        }

    # ── Non-Shopify: crawl sitemap or homepage for collections ──
    if progress_callback:
        progress_callback("⚠️ Not a Shopify store. Crawling sitemap & collections...")

    # Try sitemap first
    collection_urls = set()
    product_urls = set()

    for sitemap_path in ["/sitemap.xml", "/pub/sitemap.xml", "/sitemap_products_1.xml", "/sitemap_collections_1.xml"]:
        try:
            resp = session.get(f"{base_url}{sitemap_path}", headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml-xml")
                
                # Check for sitemap index (contains links to other sitemaps)
                sub_sitemaps = soup.find_all("sitemap")
                if sub_sitemaps:
                    for sm in sub_sitemaps:
                        loc = sm.find("loc")
                        if loc:
                            sub_url = loc.text.strip()
                            try:
                                sr = session.get(sub_url, headers=HEADERS, timeout=15)
                                if sr.status_code == 200:
                                    sub_soup = BeautifulSoup(sr.text, "lxml-xml")
                                    for url_tag in sub_soup.find_all("url"):
                                        loc_tag = url_tag.find("loc")
                                        if not loc_tag:
                                            continue
                                        url = loc_tag.text.strip()
                                        has_image = url_tag.find("image:image") is not None
                                        if "/products/" in url or has_image:
                                            product_urls.add(url)
                                        elif "/collections/" in url:
                                            collection_urls.add(url)
                            except Exception:
                                pass
                    if progress_callback:
                        progress_callback(f"📍 Sitemap index: {len(collection_urls)} collections, {len(product_urls)} products")
                    continue
                
                # Regular sitemap — detect products by image tags OR URL patterns
                for url_tag in soup.find_all("url"):
                    loc_tag = url_tag.find("loc")
                    if not loc_tag:
                        continue
                    url = loc_tag.text.strip()
                    has_image = url_tag.find("image:image") is not None
                    
                    # Skip homepage
                    parsed_url = urlparse(url)
                    if parsed_url.path in ['/', '']:
                        continue
                    
                    # Product detection: has product image, or URL contains /products/
                    if "/products/" in url:
                        product_urls.add(url)
                    elif has_image:
                        # URL with product images = likely a product page (works for Magento, WooCommerce, etc.)
                        product_urls.add(url)
                    elif "/collections/" in url or "/category/" in url:
                        collection_urls.add(url)
                    
                if progress_callback:
                    progress_callback(f"📍 Sitemap {sitemap_path}: {len(collection_urls)} collections, {len(product_urls)} product URLs (with images)")
        except Exception:
            pass
    
    # De-duplicate: remove category pages from products (pages that appear as both)
    # For Magento-style sites, filter out URLs that are clearly categories
    # Categories typically have many sub-URLs; products are leaf pages
    if product_urls:
        category_prefixes = set()
        for pu in list(product_urls):
            for pu2 in list(product_urls):
                if pu != pu2 and pu2.startswith(pu.rstrip('/') + '/'):
                    category_prefixes.add(pu)
                    break
        product_urls -= category_prefixes
        if progress_callback and category_prefixes:
            progress_callback(f"🔄 Filtered out {len(category_prefixes)} category pages, {len(product_urls)} actual products remain")

    # If we found product URLs in sitemap, scrape them directly
    if product_urls:
        if progress_callback:
            progress_callback(f"🎯 Found {len(product_urls)} product URLs in sitemap. Scraping...")

        products = []
        for i, url in enumerate(product_urls):
            if progress_callback:
                progress_callback(f"Scraping product {i+1}/{len(product_urls)}: {url}")
            try:
                product_data, session = scrape_product_page(url, session)
                products.append(product_data)
                time.sleep(0.5)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error scraping {url}: {e}")
                products.append({"url": url, "error": str(e)})

        return {
            "collection_url": site_url,
            "collection_name": "All Products",
            "website_name": website_name,
            "total_products": len(products),
            "products": products,
        }

    # Fallback: scrape each collection found
    if collection_urls:
        if progress_callback:
            progress_callback(f"📂 Found {len(collection_urls)} collections. Scraping each...")

        all_scraped = []
        for i, curl in enumerate(collection_urls):
            if progress_callback:
                progress_callback(f"📂 Collection {i+1}/{len(collection_urls)}: {curl}")
            try:
                result = scrape_collection(curl, progress_callback)
                all_scraped.extend(result.get("products", []))
            except Exception as e:
                if progress_callback:
                    progress_callback(f"Error on collection {curl}: {e}")

        return {
            "collection_url": site_url,
            "collection_name": "All Products",
            "website_name": website_name,
            "total_products": len(all_scraped),
            "products": all_scraped,
        }

    # Last resort: crawl homepage for product links
    if progress_callback:
        progress_callback("🔎 No sitemap found. Crawling homepage for product links...")

    soup, session = get_soup(base_url, session)
    links = extract_product_links(soup, base_url)

    products = []
    for i, link in enumerate(links):
        if progress_callback:
            progress_callback(f"Scraping {i+1}/{len(links)}: {link}")
        try:
            product_data, session = scrape_product_page(link, session)
            products.append(product_data)
            time.sleep(0.5)
        except Exception as e:
            products.append({"url": link, "error": str(e)})

    return {
        "collection_url": site_url,
        "collection_name": "All Products",
        "website_name": website_name,
        "total_products": len(products),
        "products": products,
    }
