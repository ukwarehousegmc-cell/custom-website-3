import google.generativeai as genai
from google.generativeai import types
import base64
import os
import time
from PIL import Image
from io import BytesIO

def configure_api():
    """Configure the Gemini API with the API key."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")
    genai.configure(api_key=api_key)

def generate_image(prompt, style="realistic", aspect_ratio="1:1"):
    """
    Generate an image using Imagen 3.0 model.
    
    Args:
        prompt: Text description of the image to generate
        style: Style of image (realistic, artistic, anime, etc.)
        aspect_ratio: Aspect ratio (1:1, 16:9, 9:16, 4:3, 3:4)
    
    Returns:
        dict with 'success', 'image_data' (base64), and 'message'
    """
    try:
        configure_api()
        
        # Enhance prompt with style
        style_prompts = {
            "realistic": "photorealistic, high quality, detailed, professional photography",
            "artistic": "artistic, creative, painterly, beautiful composition",
            "anime": "anime style, vibrant colors, detailed illustration",
            "3d": "3D rendered, cinema quality, volumetric lighting",
            "watercolor": "watercolor painting, soft colors, artistic",
            "sketch": "pencil sketch, detailed drawing, artistic",
            "digital_art": "digital art, vibrant, detailed illustration",
            "oil_painting": "oil painting, classic art style, textured",
        }
        
        style_suffix = style_prompts.get(style, style_prompts["realistic"])
        enhanced_prompt = f"{prompt}, {style_suffix}"
        
        # Use Imagen 3.0 model
        imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
        
        result = imagen.generate_images(
            prompt=enhanced_prompt,
            number_of_images=1,
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
            aspect_ratio=aspect_ratio,
        )
        
        if result.images:
            # Convert to base64
            image = result.images[0]
            buffered = BytesIO()
            image._pil_image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return {
                "success": True,
                "image_data": img_base64,
                "message": "Image generated successfully with Imagen 3.0"
            }
        else:
            return {
                "success": False,
                "image_data": None,
                "message": "No image was generated. Try a different prompt."
            }
            
    except Exception as e:
        error_msg = str(e)
        
        # Fallback to Gemini 2.0 Flash if Imagen fails
        try:
            return generate_image_gemini_fallback(prompt, style)
        except Exception as fallback_error:
            return {
                "success": False,
                "image_data": None,
                "message": f"Image generation failed: {error_msg}"
            }


def generate_image_gemini_fallback(prompt, style="realistic"):
    """
    Fallback: Generate image using Gemini 2.0 Flash with image output.
    """
    configure_api()
    
    style_prompts = {
        "realistic": "photorealistic, high quality, detailed",
        "artistic": "artistic, creative, painterly",
        "anime": "anime style, vibrant colors",
        "3d": "3D rendered, cinema quality",
        "watercolor": "watercolor painting, soft colors",
        "sketch": "pencil sketch, detailed drawing",
        "digital_art": "digital art, vibrant",
        "oil_painting": "oil painting, classic style",
    }
    
    style_suffix = style_prompts.get(style, style_prompts["realistic"])
    enhanced_prompt = f"Generate an image: {prompt}, {style_suffix}"
    
    model = genai.GenerativeModel("gemini-2.0-flash-exp")
    
    response = model.generate_content(
        enhanced_prompt,
        generation_config=types.GenerationConfig(
            response_modalities=["IMAGE", "TEXT"],
        )
    )
    
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'inline_data') and part.inline_data:
            img_data = part.inline_data.data
            if isinstance(img_data, bytes):
                img_base64 = base64.b64encode(img_data).decode("utf-8")
            else:
                img_base64 = img_data
                
            return {
                "success": True,
                "image_data": img_base64,
                "message": "Image generated with Gemini 2.0 Flash (fallback)"
            }
    
    return {
        "success": False,
        "image_data": None,
        "message": "No image was generated. Try a different prompt."
    }


def generate_multiple_images(prompt, style="realistic", count=4, aspect_ratio="1:1"):
    """
    Generate multiple images using Imagen 3.0.
    
    Args:
        prompt: Text description
        style: Style of image
        count: Number of images (1-4)
        aspect_ratio: Aspect ratio
    
    Returns:
        list of result dicts
    """
    try:
        configure_api()
        
        style_prompts = {
            "realistic": "photorealistic, high quality, detailed, professional photography",
            "artistic": "artistic, creative, painterly, beautiful composition",
            "anime": "anime style, vibrant colors, detailed illustration",
            "3d": "3D rendered, cinema quality, volumetric lighting",
            "watercolor": "watercolor painting, soft colors, artistic",
            "sketch": "pencil sketch, detailed drawing, artistic",
            "digital_art": "digital art, vibrant, detailed illustration",
            "oil_painting": "oil painting, classic art style, textured",
        }
        
        style_suffix = style_prompts.get(style, style_prompts["realistic"])
        enhanced_prompt = f"{prompt}, {style_suffix}"
        
        count = min(max(1, count), 4)
        
        imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
        
        result = imagen.generate_images(
            prompt=enhanced_prompt,
            number_of_images=count,
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
            aspect_ratio=aspect_ratio,
        )
        
        results = []
        for image in result.images:
            buffered = BytesIO()
            image._pil_image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            results.append({
                "success": True,
                "image_data": img_base64,
                "message": "Image generated successfully with Imagen 3.0"
            })
        
        return results if results else [{"success": False, "image_data": None, "message": "No images generated"}]
        
    except Exception as e:
        return [{"success": False, "image_data": None, "message": f"Error: {str(e)}"}]


def edit_image(prompt, image_base64, aspect_ratio="1:1"):
    """
    Edit an existing image using Imagen 3.0.
    
    Args:
        prompt: Edit instructions
        image_base64: Base64 encoded source image
        aspect_ratio: Output aspect ratio
    
    Returns:
        dict with result
    """
    try:
        configure_api()
        
        # Decode base64 to PIL Image
        image_data = base64.b64decode(image_base64)
        source_image = Image.open(BytesIO(image_data))
        
        imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
        
        result = imagen.edit_image(
            prompt=prompt,
            reference_images=[source_image],
            number_of_images=1,
            safety_filter_level="block_only_high",
            person_generation="allow_adult",
            aspect_ratio=aspect_ratio,
        )
        
        if result.images:
            buffered = BytesIO()
            result.images[0]._pil_image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            return {
                "success": True,
                "image_data": img_base64,
                "message": "Image edited successfully with Imagen 3.0"
            }
        
        return {"success": False, "image_data": None, "message": "Edit failed"}
        
    except Exception as e:
        return {"success": False, "image_data": None, "message": f"Error: {str(e)}"}
