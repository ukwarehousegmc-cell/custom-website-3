# 🚀 Product Listing Automation Tool

Scrape products from any website → Generate AI listings → Upload to Shopify — fully automated.

## Features

- **Web Scraper** — Scrapes any collection/category page, extracts all product data, variants, specs, prices
- **AI Listing Generator** — Uses OpenAI GPT-4o to create professional listings following your rules
- **AI Image Generator** — Uses DALL-E 3 to generate product images (optional)
- **Shopify Uploader** — Creates products with variants, tags, pricing (2x markup), inventory disabled
- **Web Dashboard** — Real-time progress tracking, logs, and results

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```
OPENAI_API_KEY=sk-your-openai-key
SHOPIFY_STORE=your-store.myshopify.com
SHOPIFY_CLIENT_ID=your-client-id
SHOPIFY_CLIENT_SECRET=your-client-secret
```

### 3. Run

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

## How It Works

1. Enter a collection URL from any reference website
2. Enter your Shopify store credentials
3. Click **Start Listing**
4. The tool will:
   - Scrape all products from the collection
   - Generate AI listings (title, description, specs, variants, tags)
   - Generate product images with DALL-E (optional)
   - Upload everything to your Shopify store as **draft** products
5. Review drafts in Shopify and publish when ready

## Pricing Rules

- Selling price = Reference price (inc VAT) × 2
- All products created as drafts
- Inventory tracking disabled on all variants

## Cost Estimate

- **GPT-4o**: ~$0.01-0.03 per product listing
- **DALL-E 3 HD**: ~$0.08 per image (2 images per product)
- **Total**: ~$0.17-0.19 per product with images, ~$0.01-0.03 without

## Tech Stack

- Python 3 + Flask
- OpenAI API (GPT-4o + DALL-E 3)
- BeautifulSoup4 for scraping
- Shopify REST Admin API
# Tue Mar 10 14:51:52 UTC 2026
