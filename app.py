"""
Product Listing Automation Tool
Flask web app for scraping products and creating Shopify listings with AI.
"""

import os
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv

load_dotenv()

from scraper import scrape_collection, scrape_product_page, scrape_full_site
from ai_generator import generate_listing, generate_images_for_product, init_openai, init_gemini
from shopify_uploader import ShopifyUploader

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")

# Global state for tracking progress
jobs = {}


class Job:
    def __init__(self, job_id, collection_url, store, client_id, client_secret, generate_images=True, image_provider="gemini", site_url=None):
        self.id = job_id
        self.collection_url = collection_url
        self.site_url = site_url
        self.store = store
        self.client_id = client_id
        self.client_secret = client_secret
        self.generate_images = generate_images
        self.image_provider = image_provider
        self.status = "pending"
        self.logs = []
        self.products_total = 0
        self.products_done = 0
        self.products_failed = 0
        self.results = []
        self.started_at = None
        self.finished_at = None
        self.stopped = False

    def log(self, message):
        entry = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        self.logs.append(entry)
        print(entry)

    def to_dict(self):
        return {
            "id": self.id,
            "collection_url": self.collection_url,
            "status": self.status,
            "products_total": self.products_total,
            "products_done": self.products_done,
            "products_failed": self.products_failed,
            "results": self.results,
            "logs": self.logs[-50:],  # Last 50 logs
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def process_job(job):
    """Background worker to process a scraping + listing job."""
    try:
        job.status = "scraping"
        job.started_at = datetime.now().isoformat()
        job.log(f"Starting job for: {job.collection_url}")

        # Initialize OpenAI
        init_openai()

        # Initialize Shopify
        uploader = ShopifyUploader(job.store, job.client_id, job.client_secret)
        uploader.authenticate()
        bundle_template_created = False
        job.log("✅ Shopify authenticated")

        # Scrape collection or full site
        if job.site_url:
            job.log("🌐 Scraping full website...")
            collection_data = scrape_full_site(
                job.site_url,
                progress_callback=lambda msg: job.log(msg)
            )
        else:
            job.log("🔍 Scraping collection page...")
            collection_data = scrape_collection(
                job.collection_url,
                progress_callback=lambda msg: job.log(msg)
            )

        collection_name = collection_data["collection_name"]
        website_name = collection_data["website_name"]
        products = collection_data["products"]
        job.products_total = len(products)
        job.log(f"📦 Found {job.products_total} products in '{collection_name}' from {website_name}")

        if not products:
            job.status = "completed"
            job.log("⚠️ No products found. Check the URL and try again.")
            job.finished_at = datetime.now().isoformat()
            return

        # Process each product
        job.status = "processing"
        for i, product_data in enumerate(products):
            if job.stopped:
                job.status = "stopped"
                job.log("🛑 Job stopped by user")
                job.finished_at = datetime.now().isoformat()
                return

            if product_data.get("error"):
                job.log(f"❌ Skipping product {i+1}: {product_data['error']}")
                job.products_failed += 1
                job.products_done += 1
                continue

            product_title = product_data.get("title", f"Product {i+1}")
            job.log(f"\n{'='*50}")
            job.log(f"📝 Processing {i+1}/{job.products_total}: {product_title}")

            try:
                # Generate AI listing
                job.log("🤖 Generating AI listing...")
                listing = generate_listing(product_data, collection_name, website_name)
                job.log(f"✅ Listing generated: {listing.get('title', 'Unknown')}")
                job.log(f"   Variants: {len(listing.get('variants', []))}")
                job.log(f"   Tags: {', '.join(listing.get('tags', []))}")

                # Generate images
                images = []
                if job.generate_images:
                    job.log(f"🎨 Generating product images with {job.image_provider.title()}...")
                    try:
                        images = generate_images_for_product(listing, product_data=product_data, log_callback=job.log, image_provider=job.image_provider)
                        job.log(f"✅ Generated {len(images)} images total")
                    except Exception as e:
                        job.log(f"⚠️ Image generation failed: {e} — continuing without images")

                # Upload to Shopify
                job.log("📤 Uploading to Shopify...")
                # Ensure bundle template exists for bundle products
                if listing.get("is_bundle") and not bundle_template_created:
                    job.log("🎨 Creating bundle product template on store...")
                    uploader.ensure_bundle_template()
                    bundle_template_created = True
                
                result = uploader.create_product(listing, images if images else None)
                job.log(f"✅ Product created: {result['title']}")
                job.log(f"   ID: {result['id']} | Variants: {result['variants_count']} | Images: {result['images_count']}")
                job.log(f"   Admin: {result['admin_url']}")

                job.results.append({
                    "status": "success",
                    "source_title": product_title,
                    "shopify_title": result["title"],
                    "shopify_id": result["id"],
                    "admin_url": result["admin_url"],
                    "variants": result["variants_count"],
                    "images": result["images_count"],
                })

            except Exception as e:
                job.log(f"❌ Failed to process '{product_title}': {e}")
                job.results.append({
                    "status": "failed",
                    "source_title": product_title,
                    "error": str(e),
                })
                job.products_failed += 1

            job.products_done += 1
            time.sleep(1)  # Rate limiting

        job.status = "completed"
        job.finished_at = datetime.now().isoformat()
        job.log(f"\n{'='*50}")
        job.log(f"🏁 Job complete! {job.products_done - job.products_failed}/{job.products_total} products created successfully.")

    except Exception as e:
        job.status = "error"
        job.log(f"💥 Job failed: {e}")
        job.finished_at = datetime.now().isoformat()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def start_job():
    data = request.json
    collection_url = data.get("collection_url", "").strip()
    site_url = data.get("site_url", "").strip()
    store = data.get("store", "").strip()
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()
    generate_images = data.get("generate_images", True)
    image_provider = data.get("image_provider", "gemini")

    if not site_url and not collection_url:
        return jsonify({"error": "Either a collection URL or full website URL is required"}), 400
    if not all([store, client_id, client_secret]):
        return jsonify({"error": "Shopify store credentials are required"}), 400

    job_id = f"job_{int(time.time())}"
    job = Job(job_id, collection_url or site_url, store, client_id, client_secret, generate_images, image_provider, site_url=site_url if site_url else None)
    jobs[job_id] = job

    # Start background thread
    thread = threading.Thread(target=process_job, args=(job,), daemon=False)
    thread.start()

    return jsonify({"job_id": job_id, "message": "Job started"})


@app.route("/api/status/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job.to_dict())


@app.route("/api/stop/<job_id>", methods=["POST"])
def stop_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    job.stopped = True
    job.log("🛑 Stop requested...")
    return jsonify({"message": "Stop signal sent"})


@app.route("/api/jobs")
def list_jobs():
    return jsonify([j.to_dict() for j in jobs.values()])


@app.route("/api/scrape-preview", methods=["POST"])
def scrape_preview():
    """Preview scrape — just get product links without full scraping."""
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL required"}), 400

    try:
        from scraper import get_soup, extract_product_links
        soup, _ = get_soup(url)
        links = extract_product_links(soup, url)
        return jsonify({"url": url, "product_count": len(links), "products": links[:20]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
