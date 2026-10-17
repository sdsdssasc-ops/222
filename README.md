# سوق المتدات
موقع Flask يتوقع أسعار ليمتدات روبلوكس ويعرض الكسبان والخسران.

## تشغيل محلي
pip install -r requirements.txt
python app.py

## النشر على Render
1. ارفع المجلد على GitHub.
2. في Render: New > Blueprint (يقرأ render.yaml) أو New > Web Service.
3. Build: pip install -r requirements.txt
4. Start: gunicorn app:app --workers 1 --threads 4 --timeout 120

متغيرات اختيارية: POOL_SIZE (افتراضي 120)، FETCH_DELAY (افتراضي 1.6).
