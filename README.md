# ATASU Intelligence 4.9.4

Geçmiş iddaa oranlarıyla benzer maç tarama, +6 bant, Kelly / Wilson, Maçkolik bülten.

## Kurulum

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`data/history.json` zip’in içinde. Yoksa motor boş açılır, çökmez.

## Çalıştır

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

Tarayıcı: http://127.0.0.1:8000

## Kullanım

1. Tarih yaz (ör. `2026-09-22`) → **Bugünün bülteni** → maça tıkla
2. Tam oran için **Linki çek**
3. **Tara** (ATASU MODEL)
4. EXCEL ORAN = birebir aynı oran
5. +6 GOL = referans bant skoru
6. Alttaki Kelly kutusu: oran + isabet % + kasa

Yarım Kelly kullan. Eşleşen maç < 30 ise yüzdelere güvenme.

## Uçlar

- GET `/api/meta` `/api/selftest` `/api/bulletin?date=2026-09-22`
- POST `/api/odds` `/api/exact-odds` `/api/plus6` `/api/kelly` `/api/match-link`

Maçkolik uçları resmi API değil; site değişirse bülten/link kırılabilir.
