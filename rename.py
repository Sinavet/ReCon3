# rename.py
import os
import zipfile
import tempfile
from pathlib import Path
from PIL import Image
import streamlit as st

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')

def process_rename_mode(uploaded_files):
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and st.button("Обработать и скачать архив", key="process_rename_btn"):
        st.subheader('Обработка изображений...')
        with tempfile.TemporaryDirectory() as temp_dir:
            all_images = []
            log = []
            st.write("[DEBUG] Старт process_rename_mode")
            # --- Сбор всех файлов ---
            for uploaded in uploaded_files:
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
            st.write(f"[DEBUG] Всего файлов для обработки: {len(all_images)}")
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
                        photos = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
                        photos_sorted = sorted(photos, key=lambda x: x.name)
                        relative_folder_path = folder.relative_to(temp_dir)
                        if len(photos_sorted) > 0:
                            for idx, photo in enumerate(photos_sorted, 1):
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
                # Архивация результата
                extracted_items = [p for p in Path(temp_dir).iterdir() if p.name != uploaded_files[0].name]
                zip_root = Path(temp_dir)
                if len(extracted_items) == 1 and extracted_items[0].is_dir():
                    zip_root = extracted_items[0]
                files_to_zip = [file for file in Path(zip_root).rglob("*") if file.is_file() and file.suffix.lower() in exts or file.name == "log.txt"]
                st.write("[DEBUG] Начинаю архивацию результата...")
                st.write(f"[DEBUG] files_to_zip: {[str(f) for f in files_to_zip]}")
                log_path = os.path.join(temp_dir, "log.txt")
                if os.path.exists(log_path):
                    files_to_zip.append(Path(log_path))
                try:
                    result_zip = os.path.join(temp_dir, "result_rename.zip")
                    with zipfile.ZipFile(result_zip, "w") as zipf:
                        for file in files_to_zip:
                            arcname = file.relative_to(zip_root)
                            zipf.write(file, arcname=arcname)
                        if os.path.exists(log_path):
                            zipf.write(log_path, arcname="log.txt")
                    st.write("[DEBUG] Архивация завершена, архив сохранён в session_state")
                    with open(result_zip, "rb") as f:
                        st.session_state["result_zip"] = f.read()
                    st.session_state["stats"] = {
                        "total": len(all_images),
                        "renamed": renamed,
                        "skipped": skipped
                    }
                    st.session_state["log"] = log
                except Exception as e:
                    st.error(f"Ошибка при архивации или чтении архива: {e}")
                    st.write(f"[DEBUG] Ошибка архивации: {e}")
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
