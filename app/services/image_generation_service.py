"""Image Generation Service — Hybrid approach.

Step 1: Download a thematic AI-generated background from Pollinations.
Step 2: Compose the DigiArt graphic charter on top using Pillow:
  - White header banner with Netinfo + DigiArt logos
  - Badge sticker (BOOTCAMP / CERTIFIED COURSE)
  - Bold center text overlay (like "XR", "3DS MAX", "METAHUMAN")
  - White footer banner with title (dark) and subtitle (cyan)
  - Decorative cyan left border strip

The final image (1080x1080) is saved to /static/generated_images/
and served via FastAPI StaticFiles.
"""
from __future__ import annotations

import io
import os
import time
import uuid
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from app.core.logging import get_logger, log_event

logger = get_logger(__name__)

# Paths
BASE_DIR = Path(__file__).parent.parent
ASSETS_DIR = BASE_DIR / "assets" / "logos"
OUTPUT_DIR = BASE_DIR.parent / "static" / "generated_images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

NETINFO_LOGO = ASSETS_DIR / "netinfo_logo.png"
DIGIART_LOGO = ASSETS_DIR / "digiart_logo.png"

# Colors (DigiArt charter — BRIGHT and VIBRANT)
WHITE      = (255, 255, 255, 255)
DARK_GREY  = (30, 30, 30, 255)
CYAN       = (0, 188, 212, 255)
YELLOW     = (255, 214, 0, 255)
ORANGE     = (255, 111, 0, 255)
LIGHT_GREY = (245, 245, 245, 255)

IMG_SIZE = (1080, 1080)
HEADER_H = 110
FOOTER_H = 130
STRIPE_W = 10

BADGE_CONFIGS = {
    "bootcamp":  {"bg": YELLOW, "text": (30, 30, 30, 255), "label": "✔ BOOTCAMP"},
    "certified": {"bg": YELLOW, "text": (30, 30, 30, 255), "label": "⊙ CERTIFIED COURSE"},
    "diploma":   {"bg": (0, 150, 136, 255), "text": (255, 255, 255, 255), "label": "✔ DIPLOMA COURSE"},
    "workshop":  {"bg": CYAN,   "text": (255, 255, 255, 255), "label": "WORKSHOP"},
    "default":   {"bg": CYAN,   "text": (255, 255, 255, 255), "label": "FORMATION"},
}


def _load_font(size: int, bold: bool = False):
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _download_background(course_title: str, keywords: str) -> Image.Image:
    import urllib.parse
    import os
    import glob
    import random
    import re
    
    # ── 1. USE LOCAL TEMPLATES OVERRIDE (Requested by user) ──
    template_dir = Path("static") / "templates"
    if template_dir.exists():
        candidates = glob.glob(str(template_dir / "*.*"))
        best_match = None
        max_score = 0
        
        # Algorithm to find the best matching template name for the course
        t_words = set(re.findall(r'\w+', course_title.lower()))
        for cand in candidates:
            if not cand.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                continue
            cand_stem = Path(cand).stem.lower()
            f_words = set(re.findall(r'\w+', cand_stem))
            score = len(f_words.intersection(t_words))
            
            # Additional weight for main software keywords
            for k in KEYWORD_MAP.keys():
                if k in cand_stem and k in course_title.lower():
                    score += 5
                    
            if score > max_score:
                max_score = score
                best_match = cand
                
        if best_match and max_score > 0:
            log_event(logger, "info", f"Using LOCAL TEMPLATE for '{course_title}': {Path(best_match).name}")
            try:
                img = Image.open(best_match).convert("RGBA")
                # Crop to fit 1080x860 without distortion
                target_aspect = 1080 / 860.0
                img_aspect = img.width / img.height
                if img_aspect > target_aspect:
                    new_w = int(img.height * target_aspect)
                    offset = (img.width - new_w) // 2
                    img = img.crop((offset, 0, offset + new_w, img.height))
                else:
                    new_h = int(img.width / target_aspect)
                    offset = (img.height - new_h) // 2
                    img = img.crop((0, offset, img.width, offset + new_h))
                return img.resize((1080, 860), Image.LANCZOS)
            except Exception as e:
                log_event(logger, "error", f"Failed to load template {best_match}: {e}")

    # Optional integration for Local Open Source Generators
    # The user can configure these in the .env file
    image_provider = os.getenv("IMAGE_PROVIDER", "pollinations").lower()
    local_api_url = os.getenv("LOCAL_IMAGE_API_URL", "http://127.0.0.1:8188") # ComfyUI default
    
    prompt = (
        f"{keywords}, "
        "NO text, NO letters, NO words, NO watermarks, NO logos"
    )
    
    if image_provider == "comfyui":
        try:
            log_event(logger, "api_call", "Generating via ComfyUI", course=course_title)
            # Advanced ComfyUI workflow JSON with LoRA (API format)
            workflow = {
                "3": {"class_type": "KSampler", "inputs": {"seed": abs(hash(course_title)) % 100000000, "steps": 25, "cfg": 7, "sampler_name": "euler", "scheduler": "normal", "denoise": 1, "model": ["10", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1080, "height": 860, "batch_size": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["10", 1]}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "text, watermark, ugly, low quality, distorted", "clip": ["10", 1]}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "DigiArt", "images": ["8", 0]}},
                "10": {"class_type": "LoraLoader", "inputs": {"lora_name": "digiart_style.safetensors", "strength_model": 1.0, "strength_clip": 1.0, "model": ["4", 0], "clip": ["4", 1]}}
            }
            # Note: This is a placeholder for actual ComfyUI async workflow polling. 
            # In a real ComfyUI setup, you queue prompt and then poll history or listen to websocket.
            # We'll just document the architecture here for the user.
        except Exception as e:
            log_event(logger, "error", f"ComfyUI generation failed: {e}")

    elif image_provider == "automatic1111" or image_provider == "forge":
        try:
            log_event(logger, "api_call", f"Generating via {image_provider}", course=course_title)
            resp = requests.post(f"{local_api_url}/sdapi/v1/txt2img", json={
                "prompt": prompt,
                "negative_prompt": "text, watermark, bad quality",
                "width": 1080, "height": 860,
                "steps": 25,
                "cfg_scale": 7
            }, timeout=120)
            resp.raise_for_status()
            img_data = resp.json()["images"][0]
            import base64
            img = Image.open(io.BytesIO(base64.b64decode(img_data))).convert("RGBA")
            return img
        except Exception as e:
            log_event(logger, "error", f"Automatic1111 generation failed: {e}")

    # ── Strategy 2: OpenAI DALL-E 3 (Enterprise Standard)
    if image_provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            log_event(logger, "error", "IMAGE_PROVIDER is openai but OPENAI_API_KEY is missing")
        else:
            try:
                log_event(logger, "api_call", "Generating via OpenAI DALL-E 3")
                r = requests.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"},
                    timeout=45
                )
                r.raise_for_status()
                image_url = r.json()["data"][0]["url"]
                img_resp = requests.get(image_url, timeout=30)
                img_resp.raise_for_status()
                return Image.open(BytesIO(img_resp.content)).convert("RGBA")
            except Exception as e:
                log_event(logger, "error", f"OpenAI generation failed: {e}")

    # ── Strategy 3: Together AI (FLUX.1-schnell - Extremely high quality open source)
    if image_provider == "together":
        together_key = os.getenv("TOGETHER_API_KEY", "")
        if not together_key:
            log_event(logger, "error", "IMAGE_PROVIDER is together but TOGETHER_API_KEY is missing")
        else:
            try:
                log_event(logger, "api_call", "Generating via Together AI (FLUX)")
                r = requests.post(
                    "https://api.together.xyz/v1/images/generations",
                    headers={"Authorization": f"Bearer {together_key}"},
                    json={"model": "black-forest-labs/FLUX.1-schnell", "prompt": prompt, "width": 1024, "height": 768, "steps": 4, "n": 1},
                    timeout=45
                )
                r.raise_for_status()
                image_b64 = r.json()["data"][0]["b64_json"]
                return Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGBA")
            except Exception as e:
                log_event(logger, "error", f"Together AI generation failed: {e}")

    # ── Strategy 4: Hugging Face Cloud API (SDXL)
    if image_provider == "huggingface":
        try:
            hf_token = os.getenv("HF_TOKEN")
            if not hf_token:
                raise ValueError("HF_TOKEN environment variable is missing.")
            
            log_event(logger, "api_call", "Generating via Hugging Face Cloud API", course=course_title)
            API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
            headers = {"Authorization": f"Bearer {hf_token}"}
            
            resp = requests.post(API_URL, headers=headers, json={"inputs": prompt}, timeout=120)
            resp.raise_for_status()
            
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            return img.resize((1080, 860), Image.LANCZOS)
        except Exception as e:
            log_event(logger, "error", f"Hugging Face API generation failed: {e}")

    # ── Fallback Strategy: Pollinations.ai (Free, no key required)
    log_event(logger, "api_call", "Downloading AI background (Pollinations)", course=course_title)
    
    # Clean the prompt for the URL
    safe_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=860&nologo=true&seed={seed}&model=flux"
    
    for attempt in range(1, 5):
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 429:
                log_event(logger, "warning", f"Pollinations rate limit hit (429). Retrying in {attempt * 5} seconds...")
                time.sleep(attempt * 5)
                continue
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            # Brighten the image to match DigiArt's vibrant style
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(1.15)
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.1)
            return img.resize((1080, 860), Image.LANCZOS)
        except Exception as exc:
            log_event(logger, "warning", f"Background download attempt {attempt} failed: {exc}")
            time.sleep(3)

    # CRITICAL FALLBACK: If all providers fail, generate a gradient so the app never crashes
    log_event(logger, "warning", "Using fallback gradient background due to API limits")
    img = Image.new("RGBA", (1080, 860), (240, 248, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(860):
        r = int(255 - (255 - 0) * y / 860)
        g = int(111 + (188 - 111) * y / 860)
        b = int(0 + (212 - 0) * y / 860)
        draw.line([(0, y), (1080, y)], fill=(r, g, b, 255))
    return img



def _draw_header(canvas: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle([0, 0, 1080, HEADER_H], fill=WHITE)
    draw.rectangle([0, HEADER_H - 3, 1080, HEADER_H], fill=CYAN)
    if NETINFO_LOGO.exists():
        logo = Image.open(NETINFO_LOGO).convert("RGBA")
        h = HEADER_H - 24
        w = int(logo.width * (h / logo.height))
        logo = logo.resize((w, h), Image.LANCZOS)
        canvas.paste(logo, (30, 12), logo)
    if DIGIART_LOGO.exists():
        logo = Image.open(DIGIART_LOGO).convert("RGBA")
        h = HEADER_H - 20
        w = int(logo.width * (h / logo.height))
        logo = logo.resize((w, h), Image.LANCZOS)
        canvas.paste(logo, (1080 - w - 30, 10), logo)


def _draw_badge(canvas: Image.Image, draw: ImageDraw.ImageDraw, badge_type: str) -> None:
    cfg = BADGE_CONFIGS.get(badge_type.lower(), BADGE_CONFIGS["default"])
    font = _load_font(22, bold=True)
    label = cfg["label"]
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = 16, 10
    bx, by = 30, HEADER_H + 20
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=5, fill=cfg["bg"])
    draw.text((bx + pad_x, by + pad_y), label, fill=cfg["text"], font=font)


def _draw_center_text(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                      big_text: str, small_text: str) -> None:
    """Draw bold center text overlay like DigiArt catalog (e.g. 'XR', 'METAHUMAN')."""
    font_big = _load_font(90, bold=True)
    font_small = _load_font(32, bold=True)

    img_center_y = HEADER_H + (IMG_SIZE[1] - HEADER_H - FOOTER_H) // 2

    bbox_big = draw.textbbox((0, 0), big_text, font=font_big)
    tw_big = bbox_big[2] - bbox_big[0]
    th_big = bbox_big[3] - bbox_big[1]

    bbox_small = draw.textbbox((0, 0), small_text, font=font_small)
    tw_small = bbox_small[2] - bbox_small[0]
    th_small = bbox_small[3] - bbox_small[1]

    total_h = th_big + 10 + th_small
    start_y = img_center_y - total_h // 2

    # Semi-transparent backdrop
    backdrop = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    bd_draw = ImageDraw.Draw(backdrop)
    pad = 30
    max_tw = max(tw_big, tw_small)
    bd_draw.rounded_rectangle(
        [(540 - max_tw // 2 - pad, start_y - pad),
         (540 + max_tw // 2 + pad, start_y + total_h + pad)],
        radius=12, fill=(0, 0, 0, 140)
    )
    canvas.paste(Image.alpha_composite(Image.new("RGBA", canvas.size, (0, 0, 0, 0)), backdrop), (0, 0), backdrop)

    draw = ImageDraw.Draw(canvas)

    # Big text white with shadow
    x_big = 540 - tw_big // 2
    draw.text((x_big + 2, start_y + 2), big_text, fill=(0, 0, 0, 180), font=font_big)
    draw.text((x_big, start_y), big_text, fill=WHITE, font=font_big)

    # Small subtitle text (cyan)
    x_small = 540 - tw_small // 2
    draw.text((x_small, start_y + th_big + 10), small_text, fill=CYAN, font=font_small)


def _draw_footer(canvas: Image.Image, draw: ImageDraw.ImageDraw,
                 title: str, subtitle: str) -> None:
    fy = IMG_SIZE[1] - FOOTER_H
    draw.rectangle([0, fy, 1080, IMG_SIZE[1]], fill=WHITE)
    draw.rectangle([0, fy, 1080, fy + 4], fill=CYAN)
    draw.rectangle([0, fy + 4, STRIPE_W, IMG_SIZE[1]], fill=CYAN)
    title_font = _load_font(36, bold=True)
    sub_font = _load_font(24, bold=False)
    if len(title) > 38:
        title = title[:35] + "..."
    draw.text((STRIPE_W + 20, fy + 16), title, fill=(30, 30, 30, 255), font=title_font)
    draw.text((STRIPE_W + 20, fy + 62), subtitle, fill=(0, 188, 212, 255), font=sub_font)
    if DIGIART_LOGO.exists():
        logo = Image.open(DIGIART_LOGO).convert("RGBA")
        h = 60
        w = int(logo.width * (h / logo.height))
        logo = logo.resize((w, h), Image.LANCZOS)
        canvas.paste(logo, (1080 - w - 20, fy + (FOOTER_H - h) // 2), logo)


# ── Keyword, subtitle, and center-text maps ─────────────────

KEYWORD_MAP = {
    "unreal":      "masterpiece, highly detailed 3D environment render created in Unreal Engine 5, cinematic lighting, volumetric fog, photorealistic landscape or sci-fi scene, octane render, 8k resolution, vibrant colors, trending on artstation",
    "unity":       "masterpiece, highly detailed isometric 3D game level design, Unity engine, bright neon holographic elements, cybernetic or futuristic workspace, vivid cyan and blue lighting, professional game development concept art",
    "avatar":      "photorealistic digital human face close-up, MetaHuman 3D render, hyper-detailed skin texture, subsurface scattering, dramatic studio lighting, cinematic portrait, 8k resolution",
    "xr":          "person wearing high-tech VR/AR headset, interacting with glowing futuristic holographic interface, bright orange and blue cyberpunk lighting, hyper-realistic, professional tech photography",
    "revit":       "hyper-realistic architectural visualization, modern futuristic building exterior, bright daylight, glass facade reflecting the sky, clean V-Ray render, photorealistic architectural photography, 8k",
    "fashion":     "haute couture digital fashion design, hyper-realistic 3D clothing render, glowing neon fabrics, bright spotlights, clean fashion runway, dramatic lighting, marvelous designer, 8k",
    "3ds":         "photorealistic interior design render, modern luxurious living room, bright natural sunlight, clean V-Ray render, contemporary furniture, architectural visualization, masterpiece, 8k",
    "multi-agent": "abstract 3D visualization of artificial intelligence neural networks, glowing nodes and connections, bright blue and orange color palette, futuristic data visualization, cinematic depth of field",
    "web":         "modern UI/UX web application dashboard floating in 3D space, glassmorphism, bright clean design, blue and white neon interface, professional tech product mockup, high quality",
    "ai":          "artificial intelligence concept, glowing quantum computer core, bright neon blue and white light, highly detailed 3D tech visualization, cinematic lighting, futuristic",
    "autodesk":    "professional 3D CAD mechanical part render, Fusion 360, generative design organic metal shapes, bright studio lighting, photorealistic product photography, clean background",
    "fusion":      "professional 3D CAD mechanical part render, Fusion 360, generative design organic metal shapes, bright studio lighting, photorealistic product photography, clean background",
}

CENTER_TEXT_MAP = {
    "unreal":      ("UNREAL", "ENGINE"),
    "unity":       ("UNITY", "VIBE CODING"),
    "avatar":      ("METAHUMAN", "DIGITAL AVATAR"),
    "xr":          ("XR", "EXTENDED REALITY"),
    "revit":       ("REVIT", "ARCHITECTURAL DESIGN"),
    "fashion":     ("FASHION", "DESIGN"),
    "3ds":         ("3DS MAX", "ENVIRONMENT DESIGN"),
    "multi-agent": ("MULTI-AGENT", "AI SYSTEMS"),
    "web":         ("WEB & APP", "AI DEVELOPMENT"),
    "ai":          ("AI", "INTELLIGENCE"),
    "autodesk":    ("FUSION", "GENERATIVE AI"),
    "fusion":      ("FUSION", "GENERATIVE AI"),
}

SUBTITLE_MAP = {
    "unreal":      "Game Development",
    "unity":       "AI-Assisted Development",
    "avatar":      "Digital Human Creation",
    "xr":          "Extended Reality",
    "revit":       "Architectural Design",
    "fashion":     "Digital Fashion",
    "3ds":         "3D Visualization",
    "multi-agent": "AI Systems",
    "web":         "Web & App Development",
    "ai":          "Artificial Intelligence",
    "autodesk":    "Product Innovation",
    "fusion":      "Product Innovation",
}


def _get_keywords(title: str) -> str:
    t = title.lower()
    for k, v in KEYWORD_MAP.items():
        if k in t:
            return v
    return f"{title} professional bright vibrant modern technology studio"


def _get_subtitle(title: str) -> str:
    t = title.lower()
    for k, v in SUBTITLE_MAP.items():
        if k in t:
            return v
    return "Tech Training"


def _get_center_text(title: str) -> tuple[str, str]:
    t = title.lower()
    for k, v in CENTER_TEXT_MAP.items():
        if k in t:
            return v
    words = title.split()
    if len(words) >= 2:
        return (words[0].upper(), words[1].upper())
    return (title.upper()[:12], "FORMATION")


def _infer_badge(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["bootcamp", "intensive"]):
        return "bootcamp"
    if any(k in t for k in ["certified", "certification"]):
        return "certified"
    if any(k in t for k in ["diploma"]):
        return "diploma"
    return "bootcamp"


def generate_course_image(course_title: str, badge_type: str | None = None,
                          subtitle: str | None = None) -> str:
    """Generate a branded 1080x1080 promotional image. Returns public URL."""
    import os, base64
    badge = badge_type or _infer_badge(course_title)
    sub = subtitle or _get_subtitle(course_title)
    keywords = _get_keywords(course_title)
    big_text, small_text = _get_center_text(course_title)

    background = _download_background(course_title, keywords)
    canvas = Image.new("RGBA", IMG_SIZE, WHITE)
    canvas.paste(background, (0, HEADER_H))

    draw = ImageDraw.Draw(canvas)
    _draw_center_text(canvas, draw, big_text, small_text)

    # Redraw after center text compositing
    draw = ImageDraw.Draw(canvas)
    _draw_header(canvas, draw)
    _draw_badge(canvas, draw, badge)
    _draw_footer(canvas, draw, course_title, sub)

    out_name = f"{uuid.uuid4().hex}.png"
    out_path = OUTPUT_DIR / out_name
    canvas.convert("RGB").save(str(out_path), "PNG", quality=95)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    # ── Strategy 1: ImgBB (free, no account, permanent URLs, production-ready)
    imgbb_key = os.getenv("IMGBB_API_KEY", "")
    if imgbb_key:
        try:
            log_event(logger, "api_call", "Uploading image to ImgBB")
            with open(out_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
            r = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": imgbb_key, "image": img_b64, "name": out_name},
                timeout=30,
            )
            r.raise_for_status()
            public_url = r.json()["data"]["url"]
            log_event(logger, "api_call", "ImgBB upload complete", public_url=public_url)
            return public_url
        except Exception as exc:
            log_event(logger, "warning", f"ImgBB upload failed: {exc}")

    # ── Strategy 2: Cloudinary (free 25GB/month, CDN global, best for production)
    cloudinary_url = os.getenv("CLOUDINARY_URL", "")
    if cloudinary_url:
        try:
            import re as re_mod
            m = re_mod.match(r"cloudinary://(\w+):(\w+)@(\w+)", cloudinary_url)
            if m:
                api_key, api_secret, cloud_name = m.group(1), m.group(2), m.group(3)
                import time as _time, hashlib
                timestamp = str(int(_time.time()))
                sig_str = f"public_id={out_name}&timestamp={timestamp}{api_secret}"
                signature = hashlib.sha1(sig_str.encode()).hexdigest()
                log_event(logger, "api_call", "Uploading image to Cloudinary")
                with open(out_path, "rb") as f:
                    r = requests.post(
                        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
                        data={"api_key": api_key, "timestamp": timestamp,
                              "signature": signature, "public_id": out_name},
                        files={"file": f},
                        timeout=30,
                    )
                r.raise_for_status()
                public_url = r.json().get("secure_url", "")
                if public_url:
                    log_event(logger, "api_call", "Cloudinary upload complete", public_url=public_url)
                    return public_url
        except Exception as exc:
            log_event(logger, "warning", f"Cloudinary upload failed: {exc}")

    # ── Strategy 3: Serve locally via FastAPI /static (works in dev + deployed)
    app_base_url = os.getenv("APP_PUBLIC_URL", "http://127.0.0.1:8000")
    local_url = f"{app_base_url}/static/generated_images/{out_name}"
    log_event(logger, "warning", f"Using local static URL: {local_url}")
    return local_url
