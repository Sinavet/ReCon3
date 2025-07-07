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

pillow_heif.register_heif_opener()

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')

st.set_page_config(page_title="Фото-бот: Переименование и конвертация", page_icon="🖼️")
st.title("🖼️ Фото-бот: Переименование и конвертация")

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
    ["Переименование фото", "Конвертация в JPG"],
    index=0 if st.session_state["mode"] == "Переименование фото" else 1,
    key="mode_radio",
    on_change=lambda: st.session_state.update({"log": [], "result_zip": None, "stats": {}})
)
st.session_state["mode"] = mode

if st.button("🔄 Начать сначала", type="primary"):
    reset_all()
    st.rerun()

MAX_SIZE_MB = 200
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

# Вместо кастомного drag-and-drop блока добавляем поясняющий текст
st.markdown(
    """
    <span style='color:#888;'>Перетащите файлы или архив на область ниже или нажмите для выбора вручную</span>
    """,
    unsafe_allow_html=True
)

uploaded_files = st.file_uploader(
    "Загрузите изображения или zip-архив (до 200 МБ)",
    type=["jpg", "jpeg", "png", "bmp", "webp", "tiff", "heic", "heif", "zip"],
    accept_multiple_files=True,
    key=st.session_state["reset_uploader"]
)

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
                        all_images.append(Path(img_temp))
                        log.append(f"🖼️ Файл {uploaded.name}: добавлен.")
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

if st.session_state["result_zip"]:
    stats = st.session_state["stats"]
    mode = st.session_state["mode"]
    if mode == "Переименование фото":
        st.success(f"Готово! Переименовано: {stats.get('renamed', 0)} из {stats.get('total', 0)} папок. Пропущено: {stats.get('skipped', 0)}")
        st.download_button(
            label="📥 Скачать архив с переименованными фото",
            data=st.session_state["result_zip"],
            file_name="renamed_photos.zip",
            mime="application/zip"
        )
    else:
        st.success(f"Готово! Конвертировано: {stats.get('converted', 0)} из {stats.get('total', 0)} файлов. Ошибок: {stats.get('errors', 0)}")
        st.download_button(
            label="📥 Скачать архив с JPG",
            data=st.session_state["result_zip"],
            file_name="converted_images.zip",
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
