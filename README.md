# ATASU Intelligence 5.1.1

Geçmiş iddaa oranlarıyla benzer maç tarama, Excel özeti, +6 bant, Kelly / Wilson, Maçkolik bülten.

## Çalıştır

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

`data/history.json` zip’in içinde. Yoksa motor boş açılır.

## Kullanım

1. Maçkolik maç linkini yapıştır → **Tara**
2. Model: kısa rapor
3. Excel: üstte küçük yorum + birebir kartlar + analog tablo
4. +6: referans bant
5. LH: harici predict

Yarım Kelly kullan. Eşleşen maç < 30 ise yüzdelere güvenme.
