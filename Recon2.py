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
from rename import process_rename_mode
from convers import process_convert_mode
from water import process_watermark_mode

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
if mode == "Переименование фото":
    process_rename_mode(uploaded_files)
elif mode == "Конвертация в JPG":
    process_convert_mode(uploaded_files)
elif mode == "Водяной знак":
    process_watermark_mode(uploaded_files, preset_choice, user_wm_file, user_wm_path, watermark_dir, pos_map, opacity, size_percent, position)

# Универсальный блок скачивания архива и лога для всех режимов
if st.session_state.get("result_zip"):
    st.download_button(
        label="📥 Скачать архив",
        data=st.session_state["result_zip"],
        file_name=(
            "renamed_photos.zip" if mode == "Переименование фото"
            else "converted_photos.zip" if mode == "Конвертация в JPG"
            else "watermarked_images.zip"
        ),
        mime="application/zip"
    )
    st.download_button(
        label="📄 Скачать лог в .txt",
        data="\n".join(st.session_state["log"]),
        file_name="log.txt",
        mime="text/plain"
    )
    if mode == "Переименование фото":
        with st.expander("Показать лог обработки"):
            st.text_area("Лог:", value="\n".join(st.session_state["log"]), height=300, disabled=True)
else:
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
