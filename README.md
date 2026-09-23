# ATASU Intelligence 5.2.0

Geçmiş iddaa oranlarıyla benzer maç tarama, Excel özeti, +6 bant, Kelly / Wilson, Maçkolik bülten ve puan durumu.

## Çalıştır

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

`data/history.json` klasörde olmalı.

## Kullanım

1. Maçkolik maç linkini yapıştır veya Günlük bülten → Tara
2. Motor maçı liginde arar: puan, form, 2.5Ü, KG
3. Tercih yalnızca bültende açık iddaa seçeneklerinden üretilir
4. 3,5 üst yoksa o market konuşulmaz

Yarım Kelly kullan. Eşleşen maç < 30 ise yüzdelere güvenme.
