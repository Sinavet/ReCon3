# convers.py
import os
import zipfile
import tempfile
from pathlib import Path
from PIL import Image
import streamlit as st

SUPPORTED_EXTS = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')

def process_convert_mode(uploaded_files):
    uploaded_files = filter_large_files(uploaded_files)
    if uploaded_files and st.button("Обработать и скачать архив", key="process_convert_btn"):
        st.subheader('Обработка изображений...')
        with tempfile.TemporaryDirectory() as temp_dir:
            all_images = []
            log = []
            st.write("[DEBUG] Старт process_convert_mode")
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
            st.write(f"[DEBUG] Всего файлов для обработки: {len(all_images)}")
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
                st.write("[DEBUG] Начинаю архивацию результата...")
                if converted_files:
                    st.write(f"[DEBUG] files_to_zip: {[src for src, rel in converted_files]}")
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
                    st.write("[DEBUG] Архивация завершена, архив сохранён в session_state")
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
                st.write("[DEBUG] Архивация завершена, архив сохранён в session_state")

    if st.session_state.get("result_zip"):
        st.download_button(
            label="📥 Скачать архив",
            data=st.session_state["result_zip"],
            file_name="converted_images.zip",
            mime="application/zip"
        )
        st.download_button(
            label="📄 Скачать лог в .txt",
            data="\n".join(st.session_state["log"]),
            file_name="log.txt",
            mime="text/plain"
        )
        with st.expander("Показать лог обработки"):
            st.text_area("Лог:", value="\n".join(st.session_state["log"]), height=300, disabled=True)
    else:
        st.write("Архив не создан")


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
