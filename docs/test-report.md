# Yakuniy test hisoboti

Sana: 2026-10-01 (foydalanuvchi vaqt zonasi: America/Los_Angeles).

## Tekshirilgan muhit

- Windows x64, Python 3.12.14.
- Haqiqiy PostgreSQL 17.11, alohida `crm_test` bazasi, localhost:55432.
- FastAPI 0.142.2, SQLAlchemy 2.1.1, psycopg 3.3.6.
- pytest 9.1.1, pytest-cov 7.1.0, Ruff 0.16.10.
- FastAPI TestClient orqali so'rovlar; SQLite ishlatilmagan.

## Natija

```text
No new upgrade operations detected.
All checks passed!
81 passed, 1 warning in 35.22s
TOTAL: 1418 statements, 77 missed, 95% coverage
API operations: 70
```

Qamrov — bajarilgan Python satrlari/statement qamrovi, barcha biznes holatlari yoki
branch coverage isboti emas. 70 amal ichiga 2 ta health endpoint ham kiradi.

| Bo'lim | Testlar |
|---|---:|
| Auth, token rotation, rollar, xodimlar | 22 |
| O'quvchilar, guruhlar, lidlar, darslar, davomat | 10 |
| Moliya, idempotency, parallel qaytarishlar | 11 |
| CLI, worker, eslatmalar, parallel qabul/refresh | 12 |
| Regressiyalar va chekka holatlar | 17 |
| Telegram, eksport, hisobotlar, health | 9 |
| **Jami** | **81** |

## Alohida tekshirilgan xavflar

- JWT/refresh bekor qilinishi, bir martalik refresh, login cheklovi, xodim bloklash.
- O'qituvchining boshqa guruh/o'quvchi va moliyaga kira olmasligi.
- Noto'g'ri/null maydon, telefon, tug'ilgan sana, pul turi, period, pagination.
- Xona/o'qituvchi jadval to'qnashuvi, sig'im va parallel qabul.
- Lid konvertatsiyasi muvaffaqiyatsiz bo'lsa, yaratilgan o'quvchining rollback qilinishi.
- To'liq davomat ro'yxati, takroriy saqlash, kelajak/bekor qilingan dars himoyasi.
- Ko'chirilgan avtomatik darsning eski slotda qayta yaratilmasligi.
- To'g'rilangan davomat uchun pending xabarning bekor qilinishi.
- Oylik hisob deduplikatsiyasi, muzlatish, foiz/summa chegirma, half-up yaxlitlash,
  guruh tugash sanasi, hisoblangan davrga retroaktiv o'zgartirishni rad etish.
- Parallel to'lov deduplikatsiyasi; parallel refund jami to'lovdan oshmasligi.
- Avans/qarz/refund balansi, receipt, daromad va qarzdorlik hisobotlari.
- Kelajakdagi chiqish sanasigacha guruhdagi o'rin va o'qituvchi ko'rinishini saqlash.
- Arxivlangan o'quvchining eski qarzini to'lash.
- Telegram webhook secret, private-chat bir martalik kod, outbox, retry,
  tokenning xato matniga chiqmasligi, ulanmagan ota-onada pending holat.
- Oldingi to'langan qarz uchun noto'g'ri eslatma ketmasligi, eslatmalar deduplikatsiyasi.
- Jadvaldagi ziddiyat billing'ni to'xtatmasligi.
- XLSX ochilishi va foydalanuvchi matnining formula sifatida bajarilmasligi.
- Admin CLI parol xeshlashi, parol tasdig'i, band login.

## Migratsiya va statik tekshiruv

- `alembic upgrade head` muvaffaqiyatli.
- Test bazasida `alembic downgrade base` → `alembic upgrade head` muvaffaqiyatli.
- Yakuniy `alembic check`: model/migratsiya farqi yo'q.
- Ruff lint muvaffaqiyatli; Python fayllari Ruff bilan formatlandi.
- OpenAPI muvaffaqiyatli qurildi va `docs/openapi.json`ga saqlandi.
- Batafsil lokal coverage: `htmlcov/index.html`.
- Mashina o'qiydigan JUnit natijasi: `.local/test-results.xml`.

## Tekshirilmagan qismlar

- Real Telegram bot tokeni va haqiqiy ota-onalar bilan yuborish tekshirilmagan;
  tashqi transport `httpx.MockTransport` orqali sinovdan o'tdi.
- GitHub Actions konfiguratsiyasi qo'shildi, remote CI ishga tushirilmagan.
- Alohida Uvicorn TCP smoke testi, katta yuklama, penetration test, uzoq davomli
  worker soak testi va production backup/restore sinovi bajarilmagan.
- Starlette TestClient `httpx` ishlatilishi kelgusida eskirishi haqida bitta
  deprecation warning berdi; u test xatosi emas. Kutubxonalar yangilanganda
  test transportini moslashtirish kerak bo'ladi.

Biznes siyosatlari va cheklovlar, jumladan hisoblangan oyga retroaktiv muzlatish
hamda qayta qabul tartibi, asosiy README'da yozilgan.
