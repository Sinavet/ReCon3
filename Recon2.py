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
import requests
import uuid

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
    "Загрузите изображения или архив (до 300 МБ, поддерживаются JPG, PNG, HEIC, ZIP и др.)",
    type=["jpg", "jpeg", "png", "bmp", "webp", "tiff", "heic", "heif", "zip"],
    accept_multiple_files=True,
    key=st.session_state["reset_uploader"]
)

MAX_SIZE_MB = 400
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

def is_file_too_large(uploaded_file):
    uploaded_file.seek(0, 2)  # Переместить в конец файла
    size = uploaded_file.tell()
    uploaded_file.seek(0)
    return size > MAX_SIZE_BYTES

def filter_large_files(uploaded_files):
    filtered = []
    for f in uploaded_files:
        if is_file_too_large(f):
            st.error(f"Файл {f.name} превышает {MAX_SIZE_MB} МБ и не будет обработан.")
        else:
            filtered.append(f)
    return filtered

# --- UI для режима Водяной знак ---
if mode == "Водяной знак":
    st.markdown("**Выберите водяной знак (PNG/JPG):**")
    import glob
    from water import apply_watermark
    watermark_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "watermarks"))
    preset_files = []
    if os.path.exists(watermark_dir):
        preset_files = [f for f in os.listdir(watermark_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    preset_choice = st.selectbox("Водяные знаки из папки watermarks/", ["Нет"] + preset_files)
    user_wm_file = st.file_uploader("Или загрузите свой PNG/JPG водяной знак", type=["png", "jpg", "jpeg"], key="watermark_upload")
    user_wm_path = None
    if user_wm_file is not None:
        tmp_dir = tempfile.gettempdir()
        user_wm_path = os.path.join(tmp_dir, f"user_wm_{user_wm_file.name}")
        with open(user_wm_path, "wb") as f:
            f.write(user_wm_file.read())
    st.sidebar.header('Настройки водяного знака')
    opacity = st.sidebar.slider('Прозрачность', 0, 100, 60) / 100.0
    size_percent = st.sidebar.slider('Размер (% от ширины фото)', 5, 80, 25)
    position = st.sidebar.selectbox('Положение', [
        'Правый нижний угол',
        'Левый нижний угол',
        'Правый верхний угол',
        'Левый верхний угол',
        'По центру',
    ])
    pos_map = {
        'Правый нижний угол': 'bottom_right',
        'Левый нижний угол': 'bottom_left',
        'Правый верхний угол': 'top_right',
        'Левый верхний угол': 'top_left',
        'По центру': 'center',
    }
    bg_color = st.sidebar.color_picker("Цвет фона предпросмотра", "#CCCCCC")

    # --- Предпросмотр водяного знака ---
    st.markdown("**Предпросмотр водяного знака:**")
    preview_img = None
    def get_first_image(uploaded_files):
        for file in uploaded_files:
            if file.name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')):
                file.seek(0)
                try:
                    return Image.open(file)
                except Exception:
                    continue
            elif file.name.lower().endswith('.zip'):
                import zipfile
                from io import BytesIO
                file.seek(0)
                with zipfile.ZipFile(file, 'r') as zf:
                    for name in zf.namelist():
                        if name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')):
                            with zf.open(name) as imgf:
                                try:
                                    return Image.open(BytesIO(imgf.read()))
                                except Exception:
                                    continue
        return None
    preview_img = get_first_image(uploaded_files) if uploaded_files else None
    if preview_img is None:
        preview_img = Image.new("RGB", (400, 300), bg_color)
    wm_path = None
    if preset_choice != "Нет":
        wm_path = os.path.join(watermark_dir, preset_choice)
    elif user_wm_file:
        tmp_dir = tempfile.gettempdir()
        wm_path = os.path.join(tmp_dir, f"user_wm_{user_wm_file.name}")
        with open(wm_path, "wb") as f:
            f.write(user_wm_file.getvalue() if hasattr(user_wm_file, 'getvalue') else user_wm_file.read())
    try:
        if wm_path:
            preview = apply_watermark(preview_img, watermark_path=wm_path, position=pos_map[position], opacity=opacity, scale=size_percent/100.0)
        else:
            preview = preview_img
        st.image(preview, caption="Предпросмотр", use_container_width=True)
    except Exception as e:
        st.warning(f"Ошибка предпросмотра: {e}")

# --- Кнопка обработки для режима Переименование фото ---
if mode == "Переименование фото" and uploaded_files:
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and st.button("Обработать и скачать архив", key="process_rename_btn"):
        import tempfile
        from pathlib import Path
        st.subheader('Обработка изображений...')
        with tempfile.TemporaryDirectory() as temp_dir:
            all_images = []
            log = []
            # --- Сбор всех файлов ---
            for uploaded in uploaded_files:
                st.write(f"Рассматриваю файл: {uploaded.name}")
                if uploaded.name.lower().endswith(".zip"):
                    zip_temp = os.path.join(temp_dir, uploaded.name)
                    with open(zip_temp, "wb") as f:
                        f.write(uploaded.read())
                    try:
                        with zipfile.ZipFile(zip_temp, "r") as zip_ref:
                            for member in zip_ref.namelist():
                                try:
                                    zip_ref.extract(member, temp_dir)
                                except Exception as e:
                                    log.append(f"❌ Не удалось извлечь {member} из {uploaded.name}: {e}")
                    except Exception as e:
                        log.append(f"❌ Ошибка открытия архива {uploaded.name}: {e}")
                        continue
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
            st.write(f"Собрано файлов для обработки: {len(all_images)}")
            if not all_images:
                st.error("Не найдено ни одного поддерживаемого изображения.")
                # Создаём пустой архив с логом ошибок
                result_zip = os.path.join(temp_dir, "result_rename.zip")
                with zipfile.ZipFile(result_zip, "w") as zipf:
                    log_path = os.path.join(temp_dir, "log.txt")
                    with open(log_path, "w", encoding="utf-8") as logf:
                        logf.write("\n".join(log))
                    zipf.write(log_path, arcname="log.txt")
                with open(result_zip, "rb") as f:
                    st.session_state["result_zip"] = f.read()
                st.session_state["stats"] = {"total": 0, "renamed": 0, "skipped": 0}
                st.session_state["log"] = log
            else:
                exts = SUPPORTED_EXTS
                renamed = 0
                skipped = 0
                folders = sorted({img.parent for img in all_images})
                if len(folders) > 0:
                    progress_bar = st.progress(0, text="Папки...")
                    for i, folder in enumerate(folders, 1):
                        st.write(f"Обрабатываю папку {i}/{len(folders)}: {folder}")
                        photos = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
                        photos_sorted = sorted(photos, key=lambda x: x.name)
                        relative_folder_path = folder.relative_to(temp_dir)
                        if len(photos_sorted) > 0:
                            for idx, photo in enumerate(photos_sorted, 1):
                                st.write(f"Переименовываю файл {photo}")
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
                        progress = min(i / len(folders), 1.0)
                        progress_bar.progress(progress, text=f"Обработано папок: {i}/{len(folders)}")
                st.write("Архивирую результат...")
                extracted_items = [p for p in Path(temp_dir).iterdir() if p.name != uploaded_files[0].name]
                zip_root = Path(temp_dir)
                if len(extracted_items) == 1 and extracted_items[0].is_dir():
                    zip_root = extracted_items[0]
                # --- Новый фильтр: исключаем исходные zip и result_*.zip ---
                files_to_zip = []
                for file in Path(zip_root).rglob("*"):
                    if file.is_file():
                        if file.suffix.lower() in SUPPORTED_EXTS or file.name == "log.txt":
                            files_to_zip.append(file)
                st.write(f"Файлы для архивации: {[str(f) for f in files_to_zip]}")
                try:
                    result_zip = os.path.join(temp_dir, "result_rename.zip")
                    with zipfile.ZipFile(result_zip, "w") as zipf:
                        for file in files_to_zip:
                            arcname = file.relative_to(zip_root)
                            zipf.write(file, arcname=arcname)
                        # Добавляем лог всегда
                        log_path = os.path.join(temp_dir, "log.txt")
                        if os.path.exists(log_path):
                            zipf.write(log_path, arcname="log.txt")
                    st.write("Читаю архив в память...")
                    with open(result_zip, "rb") as f:
                        st.session_state["result_zip"] = f.read()
                    st.session_state["stats"] = {
                        "total": len(all_images),
                        "renamed": renamed,
                        "skipped": skipped
                    }
                    st.session_state["log"] = log
                    st.write("Готово! Архив сохранён в session_state.")
                except Exception as e:
                    st.error(f"Ошибка при архивации или чтении архива: {e}")
                    # Создаём архив только с логом ошибки
                    result_zip = os.path.join(temp_dir, "result_rename.zip")
                    with zipfile.ZipFile(result_zip, "w") as zipf:
                        log.append(f"Ошибка архивации: {e}")
                        log_path = os.path.join(temp_dir, "log.txt")
                        with open(log_path, "w", encoding="utf-8") as logf:
                            logf.write("\n".join(log))
                        zipf.write(log_path, arcname="log.txt")
                    with open(result_zip, "rb") as f:
                        st.session_state["result_zip"] = f.read()
                    st.session_state["stats"] = {"total": len(all_images), "renamed": renamed, "skipped": skipped}
                    st.session_state["log"] = log

# ВНЕ блока кнопки: всегда показываем результат, если он есть
if mode == "Переименование фото" and st.session_state.get("result_zip"):
    st.download_button("Скачать архив", st.session_state["result_zip"], file_name="renamed_photos.zip", mime="application/zip")
    st.write("LOG:", st.session_state.get("log", []))
    st.write("Размер архива:", len(st.session_state["result_zip"]))
    st.download_button(
        label="📄 Скачать лог в .txt",
        data="\n".join(st.session_state["log"]),
        file_name="log.txt",
        mime="text/plain"
    )
elif mode == "Переименование фото":
    st.write("Архив не создан")

# --- Кнопка обработки для режима Конвертация в JPG ---
elif mode == "Конвертация в JPG" and uploaded_files:
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and st.button("Обработать и скачать архив", key="process_convert_btn"):
        import tempfile
        from pathlib import Path
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
                result_zip = os.path.join(temp_dir, "result_convert.zip")
                with zipfile.ZipFile(result_zip, "w") as zipf:
                    log_path = os.path.join(temp_dir, "log.txt")
                    with open(log_path, "w", encoding="utf-8") as logf:
                        logf.write("\n".join(log))
                    zipf.write(log_path, arcname="log.txt")
                with open(result_zip, "rb") as f:
                    st.session_state["result_zip"] = f.read()
                st.session_state["stats"] = {"total": 0, "converted": 0, "errors": 0}
                st.session_state["log"] = log
            else:
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
                        # Добавляем лог всегда
                        log_path = os.path.join(temp_dir, "log.txt")
                        with open(log_path, "w", encoding="utf-8") as logf:
                            logf.write("\n".join(log))
                        zipf.write(log_path, arcname="log.txt")
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
                    # Создаём архив только с логом ошибок
                    result_zip = os.path.join(temp_dir, "result_convert.zip")
                    with zipfile.ZipFile(result_zip, "w") as zipf:
                        log_path = os.path.join(temp_dir, "log.txt")
                        with open(log_path, "w", encoding="utf-8") as logf:
                            logf.write("\n".join(log))
                        zipf.write(log_path, arcname="log.txt")
                    with open(result_zip, "rb") as f:
                        st.session_state["result_zip"] = f.read()
                    st.session_state["stats"] = {"total": len(all_images), "converted": 0, "errors": errors}
                    st.session_state["log"] = log

# --- Кнопка обработки для режима Водяной знак ---
if mode == "Водяной знак":
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and (preset_choice != "Нет" or user_wm_file):
        if st.button("Обработать и скачать архив", key="process_archive_btn"):
            import tempfile
            from pathlib import Path
            import time
            st.subheader('Обработка изображений...')
            with tempfile.TemporaryDirectory() as temp_dir:
                all_images = []
                log = []
                # --- Сбор всех файлов ---
                for uploaded in uploaded_files:
                    st.write(f"Рассматриваю файл: {uploaded.name}")
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
                st.write(f"Собрано файлов для обработки: {len(all_images)}")
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
                            st.write(f"Обрабатываю файл {i}/{len(all_images)}: {img_path}")
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
                                st.write(f"Готово: {img_path}")
                            except Exception as e:
                                log.append(f"❌ {rel_path}: ошибка обработки водяного знака ({e}) (время: {time.time() - start_time:.2f} сек)")
                                st.error(f"Ошибка при обработке {rel_path}: {e}")
                                errors += 1
                            progress_bar.progress(i / len(all_images), text=f"Обработано файлов: {i}/{len(all_images)}")
                        st.write("Архивирую результат...")
                        extracted_items = [p for p in Path(temp_dir).iterdir() if p.name != uploaded_files[0].name]
                        zip_root = Path(temp_dir)
                        if len(extracted_items) == 1 and extracted_items[0].is_dir():
                            zip_root = extracted_items[0]
                        # --- Новый фильтр: исключаем исходные zip и result_*.zip ---
                        files_to_zip = []
                        for file in Path(zip_root).rglob("*"):
                            if file.is_file():
                                if file.suffix.lower() in SUPPORTED_EXTS or file.name == "log.txt":
                                    files_to_zip.append(file)
                        st.write(f"Файлы для архивации: {[str(f) for f in files_to_zip]}")
                        try:
                            result_zip = os.path.join(temp_dir, "result_watermark.zip")
                            with zipfile.ZipFile(result_zip, "w") as zipf:
                                for file in files_to_zip:
                                    arcname = file.relative_to(zip_root)
                                    zipf.write(file, arcname=arcname)
                                # Добавляем лог всегда
                                log_path = os.path.join(temp_dir, "log.txt")
                                if os.path.exists(log_path):
                                    zipf.write(log_path, arcname="log.txt")
                            st.write("Читаю архив в память...")
                            with open(result_zip, "rb") as f:
                                st.session_state["result_zip"] = f.read()
                            st.session_state["stats"] = {
                                "total": len(all_images),
                                "processed": len(processed_files),
                                "errors": errors
                            }
                            st.session_state["log"] = log
                            st.write("Готово! Архив сохранён в session_state.")
                        except Exception as e:
                            st.error(f"Ошибка при архивации или чтении архива: {e}")
                            # Создаём архив только с логом ошибки
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

# ВНЕ блока кнопки: всегда показываем результат, если он есть
if mode == "Водяной знак" and st.session_state.get("result_zip"):
    st.download_button("Скачать архив", st.session_state["result_zip"], file_name="watermarked_images.zip", mime="application/zip")
    st.write("LOG:", st.session_state.get("log", []))
    st.write("Размер архива:", len(st.session_state["result_zip"]))
    st.download_button(
        label="📄 Скачать лог в .txt",
        data="\n".join(st.session_state["log"]),
        file_name="log.txt",
        mime="text/plain"
    )
elif mode == "Водяной знак":
    st.write("Архив не создан")

if st.button("🔄 Начать сначала", type="primary"):
    reset_all()
    st.rerun()

# --- Кнопка обработки ---
# Удалён дублирующий вызов:
# if st.button("Обработать и скачать архив"):
#     ...
# (Вся логика обработки уже реализована выше внутри блока 'Водяной знак')

# --- Функция для загрузки на TransferNow ---
def upload_to_transfernow(file_path):
    url = "https://api.transfernow.net/v2/transfers"
    with open(file_path, 'rb') as f:
        files = {'files': (os.path.basename(file_path), f)}
        data = {
            'message': 'Ваш файл готов!',
            'email_from': 'noreply@photoflow.local'
        }
        response = requests.post(url, files=files, data=data)
    if response.status_code == 201:
        return response.json().get('download_url')
    else:
        return None

if st.session_state["result_zip"]:
    stats = st.session_state["stats"]
    mode = st.session_state["mode"]
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
    if not result_filename:
        result_filename = "result.zip"
    result_path = os.path.join(DOWNLOADS_DIR, result_filename)
    with open(result_path, "wb") as f:
        f.write(st.session_state["result_zip"])
    file_size_mb = os.path.getsize(result_path) / (1024 * 1024)
    st.success(msg)
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
