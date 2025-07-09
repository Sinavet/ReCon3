# water.py
import os
import zipfile
import tempfile
from pathlib import Path
from PIL import Image
import streamlit as st

def apply_watermark(
    base_image: Image.Image,
    watermark_path: str = None,
    position: str = "bottom_right",
    opacity: float = 0.5,
    scale: float = 0.2,
) -> Image.Image:
    """
    Накладывает водяной знак (PNG или текст) на изображение.
    :param base_image: Исходное изображение (PIL.Image)
    :param watermark_path: Путь к PNG-водяном знаку (или BytesIO, или None)
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
        # Поддержка BytesIO
        if isinstance(watermark_path, BytesIO):
            wm = Image.open(watermark_path).convert("RGBA")
        else:
            wm = Image.open(watermark_path).convert("RGBA")
        # Масштабирование
        wm_width = int(img.width * scale)
        wm_ratio = wm_width / wm.width
        wm_height = int(wm.height * wm_ratio)
        wm = wm.resize((wm_width, wm_height), Image.Resampling.LANCZOS)
        # Применение прозрачности
        if opacity < 1.0:
            alpha = wm.getchannel("A").point(lambda p: int(p * opacity))
            wm.putalpha(alpha)
    elif text:
        opts = text_options or {}
        font_path = opts.get("font_path", None)
        font_size = opts.get("font_size", 36)
        # Альфа-канал цвета для прозрачности
        base_color = opts.get("color", (255, 255, 255))
        if len(base_color) == 3:
            color = base_color + (int(255 * opacity),)
        else:
            color = base_color[:3] + (int(255 * opacity),)
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

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')

def process_watermark_mode(uploaded_files, preset_choice, user_wm_file, user_wm_path, watermark_dir, pos_map, opacity, size_percent, position):
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and (preset_choice != "Нет" or user_wm_file):
        if st.button("Обработать и скачать архив", key="process_archive_btn"):
            import time
            st.subheader('Обработка изображений...')
            with tempfile.TemporaryDirectory() as temp_dir:
                all_images = []
                log = []
                # --- Сбор всех файлов ---
                for uploaded in uploaded_files:
                    if uploaded.name.lower().endswith(".zip"):
                        zip_temp = os.path.join(temp_dir, uploaded.name)
                        with open(zip_temp, "wb") as f:
                            f.write(uploaded.read())
                        with zipfile.ZipFile(zip_temp, "r") as zip_ref:
                            for member in zip_ref.namelist():
                                try:
                                    zip_ref.extract(member, temp_dir)
                                except Exception as e:
                                    log.append(f"❌ Не удалось извлечь {member} из {uploaded.name}: {e}")
                        extracted = [file for file in Path(temp_dir).rglob("*") if file.is_file() and file.suffix.lower() in SUPPORTED_EXTS]
                        log.append(f"📦 Архив {uploaded.name}: найдено {len(extracted)} изображений.")
                        all_images.extend(extracted)
                    elif uploaded.name.lower().endswith(SUPPORTED_EXTS):
                        img_temp = os.path.join(temp_dir, uploaded.name)
                        with open(img_temp, "wb") as f:
                            f.write(uploaded.read())
                        all_images.append(Path(img_temp))
                        log.append(f"🖼️ Файл {uploaded.name}: добавлен.")
                    else:
                        log.append(f"❌ {uploaded.name}: не поддерживается.")
                if not all_images:
                    st.error("Не найдено ни одного поддерживаемого изображения.")
                    # Создаём пустой архив с логом ошибок
                    result_zip = os.path.join(temp_dir, "result_watermark.zip")
                    with zipfile.ZipFile(result_zip, "w") as zipf:
                        log_path = os.path.join(temp_dir, "log.txt")
                        with open(log_path, "w", encoding="utf-8") as logf:
                            logf.write("\n".join(log))
                        zipf.write(log_path, arcname="log.txt")
                    with open(result_zip, "rb") as f:
                        st.session_state["result_zip"] = f.read()
                    st.session_state["stats"] = {"total": 0, "processed": 0, "errors": 0}
                    st.session_state["log"] = log
                else:
                    watermark_path = None
                    if preset_choice != "Нет":
                        watermark_path = os.path.join(watermark_dir, preset_choice)
                    elif user_wm_file:
                        watermark_path = user_wm_path

                    processed_files = []
                    errors = 0
                    if watermark_path:
                        progress_bar = st.progress(0, text="Файлы...")
                        for i, img_path in enumerate(all_images, 1):
                            rel_path = img_path.relative_to(temp_dir)
                            out_path = os.path.join(temp_dir, str(rel_path.with_suffix('.jpg')))
                            out_dir = os.path.dirname(out_path)
                            os.makedirs(out_dir, exist_ok=True)
                            start_time = time.time()
                            try:
                                img = Image.open(img_path)
                                processed_img = apply_watermark(
                                    img,
                                    watermark_path=watermark_path,
                                    position=pos_map[position],
                                    opacity=opacity,
                                    scale=size_percent/100.0
                                )
                                processed_img.save(out_path, "JPEG", quality=100, optimize=True, progressive=True)
                                processed_files.append((out_path, rel_path.with_suffix('.jpg')))
                                log.append(f"✅ {rel_path} → {rel_path.with_suffix('.jpg')} (время: {time.time() - start_time:.2f} сек)")
                            except Exception as e:
                                log.append(f"❌ {rel_path}: ошибка обработки водяного знака ({e}) (время: {time.time() - start_time:.2f} сек)")
                                st.error(f"Ошибка при обработке {rel_path}: {e}")
                                errors += 1
                            progress_bar.progress(i / len(all_images), text=f"Обработано файлов: {i}/{len(all_images)}")
                        # Архивация только обработанных файлов
                        files_to_zip = [Path(out_path) for out_path, _ in processed_files]
                        log_path = os.path.join(temp_dir, "log.txt")
                        if os.path.exists(log_path):
                            files_to_zip.append(Path(log_path))
                        try:
                            result_zip = os.path.join(temp_dir, "result_watermark.zip")
                            with zipfile.ZipFile(result_zip, "w") as zipf:
                                for file in files_to_zip:
                                    arcname = file.relative_to(Path(temp_dir))
                                    zipf.write(file, arcname=arcname)
                            with open(result_zip, "rb") as f:
                                st.session_state["result_zip"] = f.read()
                            st.session_state["stats"] = {
                                "total": len(all_images),
                                "processed": len(processed_files),
                                "errors": errors
                            }
                            st.session_state["log"] = log
                        except Exception as e:
                            st.error(f"Ошибка при архивации или чтении архива: {e}")
                            result_zip = os.path.join(temp_dir, "result_watermark.zip")
                            with zipfile.ZipFile(result_zip, "w") as zipf:
                                log.append(f"Ошибка архивации: {e}")
                                log_path = os.path.join(temp_dir, "log.txt")
                                with open(log_path, "w", encoding="utf-8") as logf:
                                    logf.write("\n".join(log))
                                zipf.write(log_path, arcname="log.txt")
                            with open(result_zip, "rb") as f:
                                st.session_state["result_zip"] = f.read()
                            st.session_state["stats"] = {"total": len(all_images), "processed": len(processed_files), "errors": errors}
                            st.session_state["log"] = log
                    else:
                        st.error("Не удалось обработать ни одного изображения.")
                        # Создаём архив только с логом ошибок
                        result_zip = os.path.join(temp_dir, "result_watermark.zip")
                        with zipfile.ZipFile(result_zip, "w") as zipf:
                            log_path = os.path.join(temp_dir, "log.txt")
                            with open(log_path, "w", encoding="utf-8") as logf:
                                logf.write("\n".join(log))
                            zipf.write(log_path, arcname="log.txt")
                        with open(result_zip, "rb") as f:
                            st.session_state["result_zip"] = f.read()
                        st.session_state["stats"] = {"total": len(all_images), "processed": 0, "errors": errors}
                        st.session_state["log"] = log

# Фильтр больших файлов (оставить для совместимости)
def filter_large_files(uploaded_files):
    MAX_SIZE_MB = 400
    MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024
    filtered = []
    for f in uploaded_files:
        f.seek(0, 2)
        size = f.tell()
        f.seek(0)
        if size > MAX_SIZE_BYTES:
            st.error(f"Файл {f.name} превышает {MAX_SIZE_MB} МБ и не будет обработан.")
        else:
            filtered.append(f)
    return filtered
