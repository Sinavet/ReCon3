from PIL import Image, ImageDraw, ImageFont
import os
from typing import Tuple, Optional

def apply_watermark(
    base_image: Image.Image,
    watermark_path: Optional[str] = None,
    text: Optional[str] = None,
    position: str = "bottom_right",
    opacity: float = 0.5,
    scale: float = 0.2,
    text_options: Optional[dict] = None
) -> Image.Image:
    """
    Накладывает водяной знак (PNG или текст) на изображение.
    :param base_image: Исходное изображение (PIL.Image)
    :param watermark_path: Путь к PNG-водяном знаку (или None)
    :param text: Текст для текстового водяного знака (или None)
    :param position: Позиция ('top_left', 'top_right', 'center', 'bottom_left', 'bottom_right')
    :param opacity: Прозрачность (0.0-1.0)
    :param scale: Масштаб водяного знака относительно ширины base_image (0.0-1.0)
    :param text_options: dict с параметрами текста (font_path, font_size, color)
    :return: Новое изображение с водяным знаком
    """
    assert watermark_path or text, "Нужно указать watermark_path или text"
    img = base_image.convert("RGBA")
    wm = None
    if watermark_path:
        wm = Image.open(watermark_path).convert("RGBA")
        # Масштабирование
        wm_width = int(img.width * scale)
        wm_ratio = wm_width / wm.width
        wm_height = int(wm.height * wm_ratio)
        wm = wm.resize((wm_width, wm_height), Image.Resampling.LANCZOS)
        # Применение прозрачности
        if opacity < 1.0:
            alpha = wm.split()[3].point(lambda p: int(p * opacity))
            wm.putalpha(alpha)
    elif text:
        opts = text_options or {}
        font_path = opts.get("font_path", None)
        font_size = opts.get("font_size", 36)
        color = opts.get("color", (255, 255, 255, int(255 * opacity)))
        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size)
        else:
            font = ImageFont.load_default()
        # Оценка размера текста
        dummy_img = Image.new("RGBA", (10, 10))
        draw = ImageDraw.Draw(dummy_img)
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        # Масштабирование текста
        scale_factor = (img.width * scale) / text_w
        font_size_scaled = max(10, int(font_size * scale_factor))
        if font_path and os.path.exists(font_path):
            font = ImageFont.truetype(font_path, font_size_scaled)
        else:
            font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), text, font=font)
        text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
        # Создание изображения водяного знака
        wm = Image.new("RGBA", (int(text_w), int(text_h)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(wm)
        draw.text((0, 0), text, font=font, fill=color)
    else:
        raise ValueError("Не указан водяной знак")
    # Позиционирование
    positions = {
        "top_left": (0, 0),
        "top_right": (img.width - wm.width, 0),
        "center": ((img.width - wm.width) // 2, (img.height - wm.height) // 2),
        "bottom_left": (0, img.height - wm.height),
        "bottom_right": (img.width - wm.width, img.height - wm.height),
    }
    pos = positions.get(position, positions["bottom_right"])
    # Вставка водяного знака
    out = img.copy()
    out.alpha_composite(wm, dest=pos)
    return out.convert("RGB")
