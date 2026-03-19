from flask import Flask, render_template, request, jsonify
from ai_generator import generate_image, generate_multiple_images, edit_image
import os

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    data = request.get_json()
    prompt = data.get('prompt', '')
    style = data.get('style', 'realistic')
    aspect_ratio = data.get('aspect_ratio', '1:1')
    count = data.get('count', 1)
    
    if not prompt:
        return jsonify({"success": False, "message": "Please enter a prompt"})
    
    if count > 1:
        results = generate_multiple_images(prompt, style, count, aspect_ratio)
        return jsonify({"success": True, "results": results})
    else:
        result = generate_image(prompt, style, aspect_ratio)
        return jsonify(result)

@app.route('/edit', methods=['POST'])
def edit():
    data = request.get_json()
    prompt = data.get('prompt', '')
    image_data = data.get('image_data', '')
    aspect_ratio = data.get('aspect_ratio', '1:1')
    
    if not prompt or not image_data:
        return jsonify({"success": False, "message": "Prompt and image are required"})
    
    result = edit_image(prompt, image_data, aspect_ratio)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
