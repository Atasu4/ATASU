# ATASU 5.1.1

- Excel sekmesinde kısa yorum kutusu (havuz özeti + form + okuma)
- `/api/brief` → `yorum` alanı
- Maç adından iki takım parse, history.json’dan son form
- Birebir 0 olsa da analog tablo üstünde özet durur
- Ayrı excel_yorum.py gerekmez

# ATASU 5.1.0

- Bülten kutusu / tarih / üst Excel yapıştırma kalktı
- Tek Maçkolik linki Model + Excel + +6 + LH’yi doldurur
- Kısa rapor: KG, alt/üst, İY, 2. yarı, skor dağılımı
- `/api/brief`

# ATASU 4.9.4

- Parser: `2,5 Alt/Üst 1.85 1.95` doğru; etiket oran sanılmıyor
- +6: g45 / g6 proxy, iyu15=Alt iyo15=Üst
- Eşleşme: implied olasılık + ağırlıklı benzerlik
- EV, Wilson alt sınır, beklenen gol
- Kelly tam / yarım / Wilson + `/api/kelly`
- Maçkolik morebets (mac=) + ProgramDataHandler bülten listesi
- history.json yoksa boş havuzla açılır
