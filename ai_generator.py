"""
AI Generator — uses OpenAI for product listings, Gemini for image generation.
Simple prompt: reference images + product title → Gemini generates lifestyle image.
"""

import os
import io
import json
import base64
import requests
from openai import OpenAI
from PIL import Image as PILImage
from google import genai

client = None
gemini_client = None


def init_openai():
    global client
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def init_gemini():
    global gemini_client
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


LISTING_SYSTEM_PROMPT = """You are a Shopify product listing expert for a UK industrial store.
You create professional product listings from scraped product data.

STRICT RULES:
1. TITLE: Must be SEO optimised with the main keyword FIRST. Format: Main Keyword – Size (if needed) – Colour – Important Detail – Use Case
   The most important searchable keyword must always come first in the title.
   If multiple sizes/colours exist as variants, don't put them in title.

2. DESCRIPTION in this exact order:
   - Short Description (3-4 lines, NO heading above it — just the text directly, no "Short Description" heading)
   - Specifications (with heading)
   - Features (with heading)
   - Benefits (with heading)
   - Use Cases (with heading)
   - FAQ (2-3 Q&As, last section)

3. SPECIFICATIONS: Extract ALL technical data from the source, especially from the "product-specs" section. Include ALL measurements. Present specifications as an HTML table format (<table> with rows). Rewrite in your own words but keep all values accurate.

4. PRODUCT TYPE: Must match the collection name exactly.

5. TAGS: Include collection name, original product title (WITHOUT any brand names), and the reference website name (without .com/.co.uk). Website name in tags is OK — just no brand names in title/description.

6. VARIANTS: Include ALL variants exactly as shown — sizes, colours, dimensions. Do NOT miss any. Do NOT guess.

7. PRICING: Selling price = REGULAR price (inc VAT) × 2. Use the REGULAR price, NOT the member/discounted price. If multiple prices are shown, use the HIGHEST one (that's the regular price).

8. INVENTORY: Always disabled.

9. DO NOT INCLUDE (VERY IMPORTANT — STRICTLY FORBIDDEN):
   - ANY brand names from the reference website (manufacturer names, supplier names, store names)
   - The reference website name or domain
   - ANY model numbers, part numbers, SKUs, or product codes from the reference website
   - Do NOT include reference product codes in title, description, specifications, tags, or anywhere
   - If the original title contains a model/part number (e.g., "ABC-1234", "SKU: XYZ"), REMOVE it completely
   - Emails, phone numbers, postal addresses, physical addresses, contact details of ANY kind
   - Shipping details, delivery information from the reference website
   - Links, image URLs, download links
   - Supplier names, distributor names, manufacturer names, company registration numbers
   - Do NOT mention the source/supplier brand ANYWHERE — not in title, description, tags, features, specs, or FAQ
   - If the original product title contains a brand name, REMOVE it and rewrite without it
   - Replace brand references with generic terms (e.g., "premium quality" instead of brand name)

OUTPUT FORMAT — Return valid JSON:
{
  "title": "Product Title Following The Rule",
  "body_html": "<p>Short description text here without any heading...</p><h3>Specifications</h3><p>...</p><h3>Features</h3><ul>...</ul><h3>Benefits</h3><p>...</p><h3>Use Cases</h3><p>...</p><h3>FAQ</h3><p>...</p>",
  "product_type": "Collection Name",
  "tags": ["tag1", "tag2", "tag3"],
  "variants": [
    {
      "option1": "Size/Option Value",
      "price": "29.99",
      "sku": "",
      "inventory_management": null,
      "inventory_policy": "continue"
    }
  ],
  "options": [
    {
      "name": "Size",
      "values": ["Value1", "Value2"]
    }
  ]
}

IMPORTANT:
- All prices must be 2x the reference price (inc VAT)
- body_html must be valid HTML
- Include ALL variants found in the data
- If only one variant/size, still create one variant entry
"""


def generate_listing(product_data, collection_name, website_name):
    """Generate a Shopify product listing from scraped product data."""
    if not client:
        init_openai()

    context = f"""
COLLECTION NAME: {collection_name}
WEBSITE NAME: {website_name}
PRODUCT TITLE: {product_data.get('title', 'Unknown')}
PRODUCT URL: {product_data.get('url', '')}

PRICES FOUND: {json.dumps(product_data.get('prices', []))}

DESCRIPTION FROM PAGE:
{product_data.get('description', 'No description found')[:5000]}

SPECIFICATION TABLES:
{json.dumps(product_data.get('tables', []), indent=2)[:5000]}

PRODUCT SPECIFICATIONS (from product-specs section — MUST include ALL of these in Specifications as HTML table):
{json.dumps(product_data.get('product_specs', []), indent=2) if product_data.get('product_specs') else product_data.get('product_specs_text', 'None found')}

VARIANTS/OPTIONS FOUND:
{json.dumps(product_data.get('variants', []), indent=2)[:3000]}

BREADCRUMBS: {' > '.join(product_data.get('breadcrumbs', []))}

FULL PAGE TEXT (for additional context):
{product_data.get('full_text', '')[:8000]}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": LISTING_SYSTEM_PROMPT},
            {"role": "user", "content": f"Create a Shopify product listing from this scraped product data:\n\n{context}"}
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
        max_tokens=4000,
    )

    result = json.loads(response.choices[0].message.content)

    # Pass through bundle options if present
    if product_data.get("is_bundle") and product_data.get("bundle_options"):
        result["bundle_options"] = product_data["bundle_options"]
        result["base_price"] = product_data.get("base_price", 0)
        result["is_bundle"] = True
        if result.get("variants"):
            result["variants"] = [result["variants"][0]]
        if not result.get("variants"):
            result["variants"] = [{"option1": "Default", "price": str(product_data.get("base_price", "0.00"))}]

    return result


def download_reference_images(image_urls, max_images=3):
    """Download reference images from supplier website."""
    ref_images = []
    for url in image_urls[:max_images]:
        try:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }, timeout=15)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            if "png" in content_type:
                mime = "image/png"
            elif "webp" in content_type:
                mime = "image/webp"
            else:
                mime = "image/jpeg"
            ref_images.append({"data": resp.content, "mime": mime})
        except Exception:
            continue
    return ref_images


def generate_product_image(product_title, reference_images=None):
    """Generate a product image using Gemini.

    Sends reference images from the supplier website to Gemini along with
    a simple prompt asking it to create a lifestyle product image.
    """
    if not gemini_client:
        init_gemini()

    prompt = (
        f"Make image with use of this product ({product_title}) with related person. "
        f"Image size 1000 x 1000px, aspect ratio 1:1."
    )

    contents = [prompt]

    # Attach reference images so Gemini can see the actual product
    if reference_images:
        for ref in reference_images:
            try:
                img = PILImage.open(io.BytesIO(ref["data"]))
                contents.append(img)
            except Exception:
                continue

    response = gemini_client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=contents,
    )

    # Extract generated image from response
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            return part.inline_data.data

    raise Exception("No image generated by Gemini")


def force_square(image_bytes, size=1000):
    """Force any image to exact square dimensions.
    
    Center-crops to 1:1 aspect ratio first, then resizes to target size.
    This guarantees a perfect square regardless of what Gemini outputs.
    """
    img = PILImage.open(io.BytesIO(image_bytes))
    w, h = img.size

    # Center crop to square
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

    # Resize to exact target
    if img.size != (size, size):
        img = img.resize((size, size), PILImage.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def generate_images_for_product(listing_data, product_data=None, log_callback=None, **kwargs):
    """Generate product images via Gemini using reference images from supplier site.

    Downloads images from the scraped product page, sends them to Gemini as
    reference, and asks it to generate a lifestyle product photo.
    Generates 2 images per product.
    """
    images = []

    if not os.getenv("GEMINI_API_KEY"):
        if log_callback:
            log_callback("⚠️ GEMINI_API_KEY not set — skipping image generation")
        return images

    source_images = (product_data or {}).get("images", [])
    product_title = listing_data.get("title", (product_data or {}).get("title", "Product"))

    # Download reference images from supplier (max 3)
    ref_images = []
    if source_images:
        if log_callback:
            log_callback(f"📷 Downloading reference images ({len(source_images)} available)...")
        ref_images = download_reference_images(source_images, max_images=3)
        if log_callback:
            log_callback(f"✅ Downloaded {len(ref_images)} reference images")

    # Generate 2 images
    for idx in range(1, 3):
        label = "primary" if idx == 1 else "use-case"
        try:
            if log_callback:
                log_callback(
                    f"🎨 Generating image {idx} ({label}) with Gemini "
                    f"using {len(ref_images)} reference images..."
                )

            img_data = generate_product_image(product_title, ref_images if ref_images else None)

            # Force exact 1000x1000 square — no matter what Gemini outputs
            img_data = force_square(img_data, size=1000)

            images.append({"data": img_data, "filename": f"product-{label}.png", "type": label})
            if log_callback:
                log_callback(f"✅ Image {idx} generated")
        except Exception as e:
            if log_callback:
                log_callback(f"❌ Image {idx} failed: {e}")

    return images
