# ATASU Intelligence 5.7.0

Yorumcu sesi: benzer oran, Dixon-Coles, tablo, xG ve canlı pencere tek tahmin metninde erir.

## Çalıştır

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

`history.json` kökte veya `data/history.json` içinde olmalı.

## Kullanım

1. Maçkolik linki veya Masa / Bülten → Tara
2. Rapor yorumcu metnidir: nasıl biter, tek iş, ne iptal eder
3. OYNA için hâlâ içeride: hiza, birleşik ≥%63, n≥25, Wilson alt ≥%52, oran 1.30–2.20
4. Karar: OYNA veya GEÇ. Para miktarı söylemez.
5. Masa: bülteni dizer, OYNA üstte
6. Kasa: defter, isabet, CLV, PnL
7. Canlı dakika 60–75: pre-match fikir tempo bozulursa IPTAL

n < 30 ise yüzdeye tapılmaz.
