import streamlit as st
from PIL import Image, ImageEnhance
import os
import io
import zipfile

# Папка с водяными знаками
WATERMARKS_DIR = 'watermarks'

st.title('Пакетное наложение водяных знаков на фото')

# 1. Загрузка фотографий (архив или несколько файлов)
uploaded_files = st.file_uploader('Загрузите фотографии (можно несколько)', type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)

# 2. Сканируем папку с водяными знаками
if not os.path.exists(WATERMARKS_DIR):
    os.makedirs(WATERMARKS_DIR)
watermark_files = [f for f in os.listdir(WATERMARKS_DIR) if f.lower().endswith(('png', 'jpg', 'jpeg'))]

if not watermark_files:
    st.warning('Положите водяные знаки (PNG/JPG) в папку watermarks/')
else:
    watermark_name = st.selectbox('Выберите водяной знак', watermark_files)
    watermark_path = os.path.join(WATERMARKS_DIR, watermark_name)
    watermark_img = Image.open(watermark_path).convert('RGBA')
    st.image(watermark_img, caption='Водяной знак', width=200)

    # Настройки водяного знака
    st.sidebar.header('Настройки водяного знака')
    opacity = st.sidebar.slider('Прозрачность', 0, 100, 60)  # 0-100%
    size_percent = st.sidebar.slider('Размер (% от ширины фото)', 5, 80, 25)
    position = st.sidebar.selectbox('Положение', [
        'Правый нижний угол',
        'Левый нижний угол',
        'Правый верхний угол',
        'Левый верхний угол',
        'По центру',
    ])

    def get_position(img_size, wm_size, pos_name):
        x, y = 0, 0
        if pos_name == 'Правый нижний угол':
            x = img_size[0] - wm_size[0] - 10
            y = img_size[1] - wm_size[1] - 10
        elif pos_name == 'Левый нижний угол':
            x = 10
            y = img_size[1] - wm_size[1] - 10
        elif pos_name == 'Правый верхний угол':
            x = img_size[0] - wm_size[0] - 10
            y = 10
        elif pos_name == 'Левый верхний угол':
            x = 10
            y = 10
        elif pos_name == 'По центру':
            x = (img_size[0] - wm_size[0]) // 2
            y = (img_size[1] - wm_size[1]) // 2
        return (x, y)

    def apply_watermark(base_img, watermark_img, opacity, size_percent, position):
        img = base_img.convert('RGBA')
        wm = watermark_img.copy()
        # Масштабируем водяной знак
        scale = size_percent / 100.0
        new_w = int(img.size[0] * scale)
        new_h = int(wm.size[1] * (new_w / wm.size[0]))
        wm = wm.resize((new_w, new_h), Image.Resampling.LANCZOS)
        # Применяем прозрачность
        if opacity < 100:
            alpha = wm.split()[3]
            alpha = ImageEnhance.Brightness(alpha).enhance(opacity / 100.0)
            wm.putalpha(alpha)
        pos = get_position(img.size, wm.size, position)
        img.paste(wm, pos, wm)
        return img.convert('RGB')

# 3. Предпросмотр загруженных фото
if uploaded_files:
    st.subheader('Загруженные фото:')
    thumbs = []
    for file in uploaded_files:
        img = Image.open(file)
        thumbs.append(img.copy())
    st.image(thumbs, width=150, caption=[f.name for f in uploaded_files])

    # 4. Предпросмотр результата (на первом фото)
    if watermark_files:
        st.subheader('Предпросмотр результата:')
        preview_img = apply_watermark(thumbs[0], watermark_img, opacity, size_percent, position)
        st.image(preview_img, caption='Пример с водяным знаком', width=400)

    # 5. Обработка всех фото и скачивание архива
    if watermark_files and st.button('Обработать и скачать архив'):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zipf:
            for idx, file in enumerate(uploaded_files):
                img = Image.open(file)
                out_img = apply_watermark(img, watermark_img, opacity, size_percent, position)
                img_bytes = io.BytesIO()
                out_img.save(img_bytes, format='JPEG')
                img_bytes.seek(0)
                zipf.writestr(f'watermarked_{file.name}', img_bytes.read())
        zip_buffer.seek(0)
        st.download_button('Скачать архив', zip_buffer, file_name='watermarked_photos.zip', mime='application/zip')
