"""Simple CAPTCHA generation for signup protection.

Generates a random alphanumeric code and renders it as an image with
distortion to prevent automated bot signups.
"""

from __future__ import annotations

import io
import logging
import random
import string
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

from app.core.redis import redis_pool

logger = logging.getLogger(__name__)

# CAPTCHA settings
CAPTCHA_LENGTH = 6
CAPTCHA_TTL = timedelta(minutes=5)
CAPTCHA_WIDTH = 200
CAPTCHA_HEIGHT = 80

# Characters to use (excluding confusing ones like 0/O, 1/I/l)
CAPTCHA_CHARS = string.ascii_uppercase.replace('O', '').replace('I', '') + string.digits.replace('0', '').replace('1', '')


def generate_captcha_code() -> str:
    """Generate a random CAPTCHA code."""
    return ''.join(random.choices(CAPTCHA_CHARS, k=CAPTCHA_LENGTH))


async def create_captcha() -> tuple[str, bytes]:
    """Create a CAPTCHA challenge.
    
    Returns:
        tuple: (captcha_id, image_bytes)
        - captcha_id: Unique identifier to store/retrieve the code
        - image_bytes: PNG image data
    """
    code = generate_captcha_code()
    captcha_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=32))
    
    # Store in Redis with TTL
    await redis_pool.setex(
        f"captcha:{captcha_id}",
        int(CAPTCHA_TTL.total_seconds()),
        code,
    )
    
    # Generate image
    image_bytes = _render_captcha_image(code)
    
    logger.info("Generated CAPTCHA with ID %s", captcha_id)
    return captcha_id, image_bytes


async def verify_captcha(captcha_id: str, user_input: str, delete_after: bool = True) -> bool:
    """Verify a CAPTCHA response.
    
    Args:
        captcha_id: The CAPTCHA identifier
        user_input: User's input (case-insensitive)
        delete_after: Whether to delete the code after verification (default: True)
    
    Returns:
        bool: True if valid, False otherwise
    """
    if not captcha_id or not user_input:
        return False
    
    key = f"captcha:{captcha_id}"
    stored_code = await redis_pool.get(key)
    
    if not stored_code:
        logger.warning("CAPTCHA verification failed: ID %s not found or expired", captcha_id)
        return False
    
    # Case-insensitive comparison
    is_valid = stored_code.upper() == user_input.upper()
    
    # Delete after verification if requested (one-time use for signup)
    if delete_after and is_valid:
        await redis_pool.delete(key)
    
    if is_valid:
        logger.info("CAPTCHA verification successful for ID %s", captcha_id)
    else:
        logger.warning("CAPTCHA verification failed: incorrect code for ID %s", captcha_id)
    
    return is_valid


def _render_captcha_image(code: str) -> bytes:
    """Render CAPTCHA code as a distorted image.
    
    Args:
        code: The CAPTCHA code to render
    
    Returns:
        bytes: PNG image data
    """
    # Create image with white background
    image = Image.new('RGB', (CAPTCHA_WIDTH, CAPTCHA_HEIGHT), color='white')
    draw = ImageDraw.Draw(image)
    
    # Add background noise (random lines)
    for _ in range(5):
        x1 = random.randint(0, CAPTCHA_WIDTH)
        y1 = random.randint(0, CAPTCHA_HEIGHT)
        x2 = random.randint(0, CAPTCHA_WIDTH)
        y2 = random.randint(0, CAPTCHA_HEIGHT)
        draw.line([(x1, y1), (x2, y2)], fill=(200, 200, 200), width=1)
    
    # Draw the code with random positioning and colors
    try:
        # Try to use a built-in font, fall back to default if not available
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
    except Exception:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Calculate spacing
    char_width = CAPTCHA_WIDTH // len(code)
    
    for i, char in enumerate(code):
        # Random position offset
        x = char_width * i + random.randint(5, 15)
        y = random.randint(15, 30)
        
        # Random color (dark colors for readability)
        color = (
            random.randint(0, 100),
            random.randint(0, 100),
            random.randint(0, 100),
        )
        
        # Draw character
        draw.text((x, y), char, fill=color, font=font)
    
    # Add random dots for noise
    for _ in range(100):
        x = random.randint(0, CAPTCHA_WIDTH)
        y = random.randint(0, CAPTCHA_HEIGHT)
        draw.point((x, y), fill=(150, 150, 150))
    
    # Convert to bytes
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()
