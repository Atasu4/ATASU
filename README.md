# ATASU Intelligence 5.5.0

Geçmiş iddaa oranlarıyla benzer maç tarama, Dixon-Coles, Wilson/Kelly, Maçkolik bülten ve puan durumu.

## Çalıştır

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

`data/history.json` klasörde olmalı.

## Kullanım

1. Maçkolik maç linkini yapıştır veya Günlük bülten → Tara
2. Motor lig tablosu + form + 2.5Ü + KG çeker
3. Tercih yalnızca bültende açık iddaa seçeneklerinden üretilir
4. OYNA için: hiza, birleşik ≥%63, n≥25, Wilson alt ≥%52, oran 1.30–2.20
5. Stake: yarım Kelly

Yarım Kelly kullan. Eşleşen maç < 30 ise yüzdelere güvenme.
