PROFESYONEL ORAN + KOD +6 ANALIZ

Calistirma:
1) Python 3.11+ kurulu bilgisayarda klasore girin.
2) pip install -r requirements.txt
3) uvicorn app:app --host 0.0.0.0 --port 8000
4) Tarayicida http://127.0.0.1:8000 acin.

Veri disiplini:
- data/history.json: onceki uygulamadaki 11.763 gercek kayit aynen aktarildi.
- Oran motoru gizli benzerlik puani kullanmaz. Kullanici toleransi (ornegin ±0.05) icinde, girilen BUTUN oranlarin gercek gecmis kayitta bulunmasini zorunlu tutar.
- Sonucu olmayan maclar istatistige girmez.
- Kod motoru yalnizca import edilen tam 5 haneli kodlari SQLite'a kaydeder. Kod uretmez.
- +6 motoru kullanicinin yukledigi dosyadaki sabit referans bantlarini kullanir.
- Veri yoksa tahmin yapmaz.

Kod verisi import API:
POST /api/codes/import
{"rows":[{"code":"04737","league":"...","home":"...","away":"...","ht":"1-0","ft":"2-1"}]}

ATASU Intelligence v4.0 (2026-09-21)
- Premium mobile-first interface
- No-vig Market Probability Engine (raw implied probability, overround, fair probability)
- Historical similarity engine with auditable match counts
- Tolerance sensitivity test
- Sequential filter funnel
- Cross-market relationship flags
- Poisson total-goal calibration only when a complete O/U pair exists
- Home/away goal split fitted numerically to margin-cleaned 1X2; no default/fabricated lambda
- Missing required data returns VERI YOK instead of guessed values
