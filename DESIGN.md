# ATASU — tasarım

Sıkı otel / masaüstü: serif marka, mono veri, şampanya altın çizgi. Köşe yok.

## Renk

| Token | Hex | Kullanım |
|---|---|---|
| Ink | `#07080A` | Sayfa zemini |
| Void | `#0C0D10` | Input, KPI hücre |
| Paper | `#101217` | Kart |
| Gold | `#E4C98A` | Marka, aktif sekme, KPI rakam |
| Gold 2 | `#B8945A` | Kicker, tercih çerçeve |
| Line | `#D6BA84` @ 16% | İnce çerçeve |
| Line 2 | `#D6BA84` @ 28% | Hover çerçeve |
| Fog | `#8E918B` | Yardımcı yazı |
| Snow | `#F6F1E6` | Ana metin |
| Go | `#B7E4B0` | Olumlu |
| Stop | `#E89AA3` | Sil / hata |
| Tercih yazı | `#F4E6C0` | Kupon kutusu |

## Tipografi

- Marka / rakam: **Cormorant Garamond** 500–600, 28–40px
- Arayüz: **Manrope** 400–600, 11–15px
- Oran / tablo: **IBM Plex Mono** 400–500, 9–13px
- Kicker: 10px, letter-spacing 0.2em, uppercase

## Ölçü

- İçerik max **1080px**
- Kart padding **26 / 24**
- Yapışkan başlık, blur 16px
- Gölge kart: `0 24px 60px rgba(0,0,0,.35)`
- Radius: **0**
- Sekme harf aralığı **0.16em**

## Zemin

```
radial-gradient(ellipse 70% 36% at 50% -8%, rgba(184,148,90,.16), transparent 52%)
linear-gradient(180deg, #0E1014 0%, #07080A 28%)
```
