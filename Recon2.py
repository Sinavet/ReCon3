import streamlit as st
import os
import zipfile
import tempfile
from pathlib import Path
from PIL import Image
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_SUPPORT = True
except ImportError:
    HEIF_SUPPORT = False
    st.warning("Для поддержки HEIC/HEIF установите пакет pillow-heif: pip install pillow-heif")
import shutil
from io import BytesIO

pillow_heif.register_heif_opener()

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')

st.set_page_config(page_title="PhotoFlow: Умная обработка изображений")
st.title("PhotoFlow: Умная обработка изображений")

with st.expander("ℹ️ Инструкция и ответы на вопросы"):
    st.markdown("""
    **Как пользоваться ботом:**
    1. Выберите режим работы.
    2. Загрузите изображения или архив.
    3. Дождитесь обработки и скачайте результат.

    **FAQ:**
    - *Почему не все фото обработались?*  
      Возможно, некоторые файлы были повреждены или не поддерживаются.
    - *Что делать, если архив не скачивается?*  
      Попробуйте уменьшить размер архива или разделить файлы на несколько частей.
    """)

if "reset_uploader" not in st.session_state:
    st.session_state["reset_uploader"] = 0
if "log" not in st.session_state:
    st.session_state["log"] = []
if "result_zip" not in st.session_state:
    st.session_state["result_zip"] = None
if "stats" not in st.session_state:
    st.session_state["stats"] = {}
if "mode" not in st.session_state:
    st.session_state["mode"] = "Переименование фото"

def reset_all():
    st.session_state["reset_uploader"] += 1
    st.session_state["log"] = []
    st.session_state["result_zip"] = None
    st.session_state["stats"] = {}
    st.session_state["mode"] = "Переименование фото"

mode = st.radio(
    "Выберите режим работы:",
    ["Переименование фото", "Конвертация в JPG", "Водяной знак"],
    index=0 if st.session_state["mode"] == "Переименование фото" else (1 if st.session_state["mode"] == "Конвертация в JPG" else 2),
    key="mode_radio",
    on_change=lambda: st.session_state.update({"log": [], "result_zip": None, "stats": {}})
)
st.session_state["mode"] = mode

st.markdown(
    """
    <span style='color:#888;'>Перетащите файлы или архив на область ниже или нажмите для выбора вручную</span>
    """,
    unsafe_allow_html=True
)

uploaded_files = st.file_uploader(
    "Загрузите изображения или архив (до 1 ГБ, поддерживаются JPG, PNG, HEIC, ZIP и др.)",
    type=["jpg", "jpeg", "png", "bmp", "webp", "tiff", "heic", "heif", "zip"],
    accept_multiple_files=True,
    key=st.session_state["reset_uploader"]
)

# --- UI для режима Водяной знак ---
if mode == "Водяной знак":
    st.markdown("**Выберите водяной знак:**")
    import glob
    from water import apply_watermark
    # Папка с предустановленными водяными знаками
    watermark_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "watermarks"))
    st.write("Текущая рабочая директория:", os.getcwd())
    st.write("Содержимое watermarks:", os.listdir(watermark_dir) if os.path.exists(watermark_dir) else "Папка не найдена")
    preset_files = glob.glob(os.path.join(watermark_dir, "*.png")) if os.path.exists(watermark_dir) else []
    preset_names = [os.path.basename(f) for f in preset_files]
    preset_choice = st.selectbox("Предустановленные", ["Нет"] + preset_names)
    user_wm_file = st.file_uploader("Или загрузите свой PNG-водяной знак", type=["png"], key="user_wm")
    user_wm_bytes = None
    user_wm_path = None
    user_wm_filename = None
    if user_wm_file is not None:
        user_wm_bytes = user_wm_file.read()
        user_wm_filename = user_wm_file.name
        # Сохраняем временный файл для предпросмотра
        tmp_dir = tempfile.gettempdir()
        user_wm_path = os.path.join(tmp_dir, f"user_wm_{user_wm_filename}")
        with open(user_wm_path, "wb") as f:
            f.write(user_wm_bytes)
    st.markdown("**Или текстовый водяной знак:**")
    text_wm = st.text_input("Текст водяного знака", "")
    col1, col2 = st.columns(2)
    with col1:
        text_color = st.color_picker("Цвет текста", "#FFFFFF")
    with col2:
        text_size = st.slider("Размер шрифта", 10, 120, 36)
    # Параметры водяного знака
    st.markdown("**Параметры водяного знака:**")
    col1, col2, col3 = st.columns(3)
    with col1:
        position = st.selectbox("Позиция", [
            ("Левый верх", "top_left"),
            ("Правый верх", "top_right"),
            ("Центр", "center"),
            ("Левый низ", "bottom_left"),
            ("Правый низ", "bottom_right")
        ], format_func=lambda x: x[0])[1]
    with col2:
        opacity = st.slider("Прозрачность", 0, 100, 50) / 100.0
    with col3:
        scale = st.slider("Масштаб (% от ширины)", 5, 50, 20) / 100.0

    # --- Предпросмотр водяного знака ---
    st.markdown("**Предпросмотр водяного знака:**")
    preview_img = None
    if uploaded_files:
        try:
            preview_file = uploaded_files[0]
            preview_img = Image.open(preview_file)
        except Exception:
            preview_img = Image.new("RGB", (400, 300), (200, 200, 200))
    else:
        preview_img = Image.new("RGB", (400, 300), (200, 200, 200))
    wm_path = None
    if preset_choice != "Нет":
        wm_path = os.path.join(watermark_dir, preset_choice)
    elif user_wm_path:
        wm_path = user_wm_path
    text_opts = {
        "font_size": text_size,
        "color": tuple(int(text_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (int(255 * opacity),)
    }
    try:
        if wm_path:
            preview = apply_watermark(preview_img, watermark_path=wm_path, position=position, opacity=opacity, scale=scale)
        elif text_wm:
            preview = apply_watermark(preview_img, text=text_wm, position=position, opacity=opacity, scale=scale, text_options=text_opts)
        else:
            preview = preview_img
        st.image(preview, caption="Предпросмотр", use_column_width=True)
    except Exception as e:
        st.warning(f"Ошибка предпросмотра: {e}")

if st.button("🔄 Начать сначала", type="primary"):
    reset_all()
    st.rerun()

MAX_SIZE_MB = 3072
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

if uploaded_files and not st.session_state["result_zip"]:
    # Проверка размера файлов
    oversize = [f for f in uploaded_files if hasattr(f, 'size') and f.size > MAX_SIZE_BYTES]
    if oversize:
        st.error(f"Файл(ы) превышают лимит {MAX_SIZE_MB} МБ: {[f.name for f in oversize]}")
    else:
        with st.spinner("Обработка файлов..."):
            with tempfile.TemporaryDirectory() as temp_dir:
                all_images = []
                log = st.session_state.get("log", []).copy()
                # --- Сбор всех файлов ---
                for uploaded in uploaded_files:
                    if hasattr(uploaded, 'size') and uploaded.size > MAX_SIZE_BYTES:
                        log.append(f"❌ {uploaded.name}: превышает лимит {MAX_SIZE_MB} МБ.")
                        continue
                    if uploaded.name.lower().endswith(".zip"):
                        zip_temp = os.path.join(temp_dir, uploaded.name)
                        with open(zip_temp, "wb") as f:
                            f.write(uploaded.read())
                        with zipfile.ZipFile(zip_temp, "r") as zip_ref:
                            zip_ref.extractall(temp_dir)
                        extracted = [file for file in Path(temp_dir).rglob("*") if file.is_file() and file.suffix.lower() in SUPPORTED_EXTS]
                        log.append(f"📦 Архив {uploaded.name}: найдено {len(extracted)} изображений.")
                        all_images.extend(extracted)
                    elif uploaded.name.lower().endswith(SUPPORTED_EXTS):
                        img_temp = os.path.join(temp_dir, uploaded.name)
                        with open(img_temp, "wb") as f:
                            f.write(uploaded.read())
                        # Проверка размера файла после копирования
                        if os.path.getsize(img_temp) == 0:
                            log.append(f"❌ {uploaded.name}: файл скопирован с нулевым размером!")
                        else:
                            log.append(f"🖼️ Файл {uploaded.name}: добавлен, размер: {os.path.getsize(img_temp)} байт.")
                        all_images.append(Path(img_temp))
                    else:
                        log.append(f"❌ {uploaded.name}: не поддерживается.")
                if not all_images:
                    st.error("Не найдено ни одного поддерживаемого изображения.")
                else:
                    if mode == "Переименование фото":
                        exts = SUPPORTED_EXTS
                        renamed = 0
                        skipped = 0
                        folders = sorted({img.parent for img in all_images})
                        progress_bar = st.progress(0, text="Папки...")
                        for i, folder in enumerate(folders):
                            photos = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
                            relative_folder_path = folder.relative_to(temp_dir)
                            if len(photos) > 0:
                                for idx, photo in enumerate(sorted(photos), 1):
                                    new_name = f"{idx}{photo.suffix.lower()}"
                                    new_path = photo.parent / new_name
                                    relative_photo_path = photo.relative_to(temp_dir)
                                    relative_new_path = new_path.relative_to(temp_dir)
                                    if new_path.exists() and new_path != photo:
                                        log.append(f"Пропущено: Файл '{relative_new_path}' уже существует.")
                                        skipped += 1
                                    else:
                                        photo.rename(new_path)
                                        log.append(f"Переименовано: '{relative_photo_path}' -> '{relative_new_path}'")
                                        renamed += 1
                            else:
                                log.append(f"Инфо: В папке '{relative_folder_path}' нет фото.")
                                skipped += 1
                            progress_bar.progress((i + 1) / len(folders), text=f"Обработано папок: {i + 1}/{len(folders)}")
                        extracted_items = [p for p in Path(temp_dir).iterdir() if p.name != uploaded_files[0].name]
                        zip_root = Path(temp_dir)
                        if len(extracted_items) == 1 and extracted_items[0].is_dir():
                            zip_root = extracted_items[0]
                        result_zip = os.path.join(temp_dir, "result_rename.zip")
                        shutil.make_archive(base_name=result_zip[:-4], format='zip', root_dir=str(zip_root))
                        with open(result_zip, "rb") as f:
                            st.session_state["result_zip"] = f.read()
                        st.session_state["stats"] = {
                            "total": len(all_images),
                            "renamed": renamed,
                            "skipped": skipped
                        }
                        st.session_state["log"] = log
                    elif mode == "Конвертация в JPG":
                        converted_files = []
                        errors = 0
                        progress_bar = st.progress(0, text="Файлы...")
                        for i, img_path in enumerate(all_images, 1):
                            rel_path = img_path.relative_to(temp_dir)
                            out_path = os.path.join(temp_dir, str(rel_path.with_suffix('.jpg')))
                            out_dir = os.path.dirname(out_path)
                            os.makedirs(out_dir, exist_ok=True)
                            try:
                                img = Image.open(img_path)
                                icc_profile = img.info.get('icc_profile')
                                img = img.convert("RGB")
                                img.save(out_path, "JPEG", quality=100, optimize=True, progressive=True, icc_profile=icc_profile)
                                converted_files.append((out_path, rel_path.with_suffix('.jpg')))
                                log.append(f"✅ {rel_path} → {rel_path.with_suffix('.jpg')}")
                            except Exception as e:
                                log.append(f"❌ {rel_path}: ошибка конвертации ({e})")
                                errors += 1
                            progress_bar.progress(i / len(all_images), text=f"Обработано файлов: {i}/{len(all_images)}")
                        if converted_files:
                            result_zip = os.path.join(temp_dir, "result_convert.zip")
                            with zipfile.ZipFile(result_zip, "w") as zipf:
                                for src, rel in converted_files:
                                    zipf.write(src, arcname=rel)
                            with open(result_zip, "rb") as f:
                                st.session_state["result_zip"] = f.read()
                            st.session_state["stats"] = {
                                "total": len(all_images),
                                "converted": len(converted_files),
                                "errors": errors
                            }
                            st.session_state["log"] = log
                        else:
                            st.error("Не удалось конвертировать ни одного изображения.")
                            st.session_state["log"] = log
                    elif mode == "Водяной знак":
                        log = st.session_state.get("log", []).copy()
                        processed_files = []
                        errors = 0
                        progress_bar = st.progress(0, text="Файлы...")
                        # Определяем параметры водяного знака
                        wm_path = None
                        user_wm_path = None
                        if preset_choice != "Нет":
                            wm_path = os.path.join(watermark_dir, preset_choice)
                        elif user_wm_bytes and user_wm_filename:
                            # Сохраняем временный файл для обработки
                            tmp_dir = tempfile.gettempdir()
                            user_wm_path = os.path.join(tmp_dir, f"user_wm_{user_wm_filename}")
                            with open(user_wm_path, "wb") as f:
                                f.write(user_wm_bytes)
                            wm_path = user_wm_path
                        elif text_wm:
                            pass  # текстовый вотермарк
                        else:
                            st.error("Выберите или загрузите водяной знак, либо введите текст!")
                            log.append("❌ Не выбран ни один водяной знак для обработки.")
                            st.session_state["log"] = log
                            st.session_state["stats"] = {"total": len(all_images), "processed": 0, "errors": len(all_images)}
                            st.stop()
                        text_opts = {
                            "font_size": text_size,
                            "color": tuple(int(text_color.lstrip('#')[i:i+2], 16) for i in (0, 2, 4)) + (int(255 * opacity),)
                        }
                        for i, img_path in enumerate(all_images, 1):
                            rel_path = img_path.relative_to(temp_dir)
                            out_path = os.path.join(temp_dir, str(rel_path.with_suffix('.jpg')))
                            out_dir = os.path.dirname(out_path)
                            os.makedirs(out_dir, exist_ok=True)
                            try:
                                img = Image.open(img_path)
                                # Диагностика для предустановленного PNG
                                if wm_path:
                                    # Проверка регистра имени файла
                                    actual_files = os.listdir(os.path.dirname(wm_path))
                                    if os.path.basename(wm_path) not in actual_files:
                                        log.append(f"❌ {rel_path}: файл водяного знака {wm_path} не найден (проверь регистр имени)")
                                        errors += 1
                                        continue
                                    if not os.path.exists(wm_path):
                                        log.append(f"❌ {rel_path}: файл водяного знака не найден: {wm_path}")
                                        errors += 1
                                        continue
                                    elif os.path.getsize(wm_path) == 0:
                                        log.append(f"❌ {rel_path}: файл водяного знака пустой: {wm_path}")
                                        errors += 1
                                        continue
                                    else:
                                        log.append(f"✅ Водяной знак найден: {wm_path}, размер: {os.path.getsize(wm_path)} байт")
                                        try:
                                            with Image.open(wm_path) as test_img:
                                                test_img.verify()
                                        except Exception as e:
                                            log.append(f"❌ {rel_path}: не удалось открыть водяной знак {wm_path}: {e}")
                                            errors += 1
                                            continue
                                    result = apply_watermark(img, watermark_path=wm_path, position=position, opacity=opacity, scale=scale)
                                elif text_wm:
                                    result = apply_watermark(img, text=text_wm, position=position, opacity=opacity, scale=scale, text_options=text_opts)
                                else:
                                    log.append(f"❌ {rel_path}: не выбран водяной знак")
                                    errors += 1
                                    continue
                                result = result.convert("RGB")  # Гарантируем RGB для JPEG
                                result.save(out_path, "JPEG", quality=100, optimize=True, progressive=True)
                                processed_files.append((out_path, rel_path.with_suffix('.jpg')))
                                log.append(f"✅ {rel_path} → {rel_path.with_suffix('.jpg')}")
                            except Exception as e:
                                log.append(f"❌ {rel_path}: ошибка водяного знака ({e})")
                                errors += 1
                            progress_bar.progress(i / len(all_images), text=f"Обработано файлов: {i}/{len(all_images)}")
                        if processed_files:
                            result_zip = os.path.join(temp_dir, "result_watermark.zip")
                            with zipfile.ZipFile(result_zip, "w") as zipf:
                                for src, rel in processed_files:
                                    zipf.write(src, arcname=rel)
                            with open(result_zip, "rb") as f:
                                st.session_state["result_zip"] = f.read()
                            st.session_state["stats"] = {
                                "total": len(all_images),
                                "processed": len(processed_files),
                                "errors": errors
                            }
                            st.session_state["log"] = log
                        else:
                            st.error("Не удалось обработать ни одного изображения.")
                            st.session_state["log"] = log
                            st.write(log)  # Выводим лог для отладки

if st.session_state["result_zip"]:
    stats = st.session_state["stats"]
    mode = st.session_state["mode"]
    # --- Новый блок: определяем способ скачивания ---
    DOWNLOADS_DIR = "downloads"
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    result_filename = None
    if mode == "Переименование фото":
        result_filename = "renamed_photos.zip"
        msg = f"Готово! Переименовано: {stats.get('renamed', 0)} из {stats.get('total', 0)} папок. Пропущено: {stats.get('skipped', 0)}"
    elif mode == "Конвертация в JPG":
        result_filename = "converted_images.zip"
        msg = f"Готово! Конвертировано: {stats.get('converted', 0)} из {stats.get('total', 0)} файлов. Ошибок: {stats.get('errors', 0)}"
    elif mode == "Водяной знак":
        result_filename = "watermarked_images.zip"
        msg = f"Готово! Обработано: {stats.get('processed', 0)} из {stats.get('total', 0)} файлов. Ошибок: {stats.get('errors', 0)}"
    # Сохраняем файл на диск
    result_path = os.path.join(DOWNLOADS_DIR, result_filename)
    with open(result_path, "wb") as f:
        f.write(st.session_state["result_zip"])
    file_size_mb = os.path.getsize(result_path) / (1024 * 1024)
    st.success(msg)
    if file_size_mb > 100:
        st.markdown(f"[📥 Скачать архив]({result_path}) (через статическую ссылку, {file_size_mb:.1f} МБ)")
        st.info("Если скачивание не начинается, скопируйте ссылку и откройте в новой вкладке. Для больших файлов download_button не используется.")
    else:
        with open(result_path, "rb") as f:
            st.download_button(
                label="📥 Скачать архив",
                data=f.read(),
                file_name=result_filename,
                mime="application/zip"
            )
    with st.expander("Показать лог обработки"):
        st.text_area("Лог:", value="\n".join(st.session_state["log"]), height=300, disabled=True)
        st.download_button(
            label="📄 Скачать лог в .txt",
            data="\n".join(st.session_state["log"]),
            file_name="log.txt",
            mime="text/plain"
        )
