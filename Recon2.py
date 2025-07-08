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
    key="main_upload"
)

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

    # --- Кнопка обработки ---
    if st.button("Обработать и скачать архив", key="process_archive_btn"):
        if not (preset_choice != "Нет" or user_wm_file):
            st.error("Выберите или загрузите водяной знак!")
        else:
            st.subheader('Обработка изображений...')
            processed_files = []
            errors = 0
            log = []
            # Определяем путь к водяному знаку
            # (wm_path уже определён выше)
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w') as zipf:
                for file in uploaded_files:
                    if file.name.lower().endswith('.zip'):
                        file.seek(0)
                        try:
                            with zipfile.ZipFile(file, 'r') as zf:
                                for name in zf.namelist():
                                    if name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')):
                                        with zf.open(name) as imgf:
                                            try:
                                                img = Image.open(BytesIO(imgf.read())).convert('RGBA')
                                                result = apply_watermark(
                                                    img,
                                                    watermark_path=wm_path,
                                                    position=pos_map[position],
                                                    opacity=opacity,
                                                    scale=size_percent/100.0
                                                )
                                                out_img = result.convert('RGB')
                                                img_bytes = BytesIO()
                                                out_img.save(img_bytes, format='JPEG')
                                                img_bytes.seek(0)
                                                zipf.writestr(f'watermarked_{os.path.basename(name)}', img_bytes.read())
                                                processed_files.append(name)
                                                log.append(f"✅ {name} обработан из архива {file.name}")
                                            except Exception as e:
                                                errors += 1
                                                log.append(f"❌ {name} из {file.name}: ошибка обработки ({e})")
                        except Exception as e:
                            errors += 1
                            log.append(f"❌ {file.name}: ошибка чтения архива ({e})")
                    elif file.name.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.heic', '.heif')):
                        try:
                            file.seek(0)
                            img = Image.open(file).convert('RGBA')
                            result = apply_watermark(
                                img,
                                watermark_path=wm_path,
                                position=pos_map[position],
                                opacity=opacity,
                                scale=size_percent/100.0
                            )
                            out_img = result.convert('RGB')
                            img_bytes = BytesIO()
                            out_img.save(img_bytes, format='JPEG')
                            img_bytes.seek(0)
                            zipf.writestr(f'watermarked_{file.name}', img_bytes.read())
                            processed_files.append(file.name)
                            log.append(f"✅ {file.name} обработан")
                        except Exception as e:
                            errors += 1
                            log.append(f"❌ {file.name}: ошибка обработки ({e})")
                    else:
                        log.append(f"❌ {file.name}: не поддерживается (не изображение и не архив)")
            zip_buffer.seek(0)
            st.session_state["result_zip"] = zip_buffer.getvalue()
            st.session_state["stats"] = {
                "total": len(processed_files),
                "processed": len(processed_files),
                "errors": errors
            }
            st.session_state["log"] = log

if st.button("🔄 Начать сначала", type="primary"):
    reset_all()
    st.rerun()

MAX_SIZE_MB = 3072
MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

# Удаляю автоматическую обработку файлов
# Было:
# if uploaded_files and not st.session_state["result_zip"]:
#     ...
# Теперь обработка только по кнопке ниже
# (Весь код обработки файлов вне блока с кнопкой удалён)

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
