# O'quv markaz CRM — FastAPI + PostgreSQL

Faqat backend. Frontend yo'q. ZIP ichidagi 13 bo'lim asosida autentifikatsiya, xodimlar,
o'quvchilar, ota-onalar, lidlar, kurslar, guruhlar, darslar, davomat, moliya,
Telegram navbati, hisobotlar va audit amalga oshirilgan.

## Docker bilan ishga tushirish

Docker Engine va Docker Compose kerak.

1. `.env.example` faylini `.env` nomi bilan nusxalang.
2. `POSTGRES_PASSWORD` uchun kuchli, URL-safe parol, `JWT_SECRET` uchun tasodifiy
   kamida 32 belgili qiymat yozing. Masalan: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
   Namuna qiymatlarini production'da ishlatmang. `.env` Git'ga kiritilmaydi.
3. Ishga tushiring:

```sh
docker compose up --build -d
docker compose exec api python -m app.cli create-admin --username admin --name Administrator
```

Admin paroli terminalda ikki marta so'raladi; kamida 12 belgi. Tayyor/default admin
paroli yo'q. Migratsiya alohida servisda bajariladi, keyin API va worker boshlanadi.

- Swagger: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc
- OpenAPI: http://127.0.0.1:8000/openapi.json
- Liveness: `/health/live`; PostgreSQL/migratsiya readiness: `/health/ready`.
- API prefiksi: `/api/v1`.

Compose PostgreSQL portini tashqariga ochmaydi; API faqat localhost'ga bog'langan.
Tashqi serverda HTTPS reverse proxy orqali chiqaring. Ma'lumotlar `postgres_data`
volume'ida qoladi. `docker compose down -v` bazani o'chiradi — odatiy to'xtatish uchun
`docker compose down` yetarli.

## Docker'siz ishga tushirish

Python 3.12+ va PostgreSQL 17 tavsiya etiladi. Alohida `crm` bazasi/roli yarating,
`.env` ichidagi `DATABASE_URL`ni ularga moslang.

```sh
python -m venv .venv-crm
# Windows: .venv-crm\Scripts\Activate.ps1
# Linux/macOS: source .venv-crm/bin/activate
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m app.cli create-admin
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Boshqa terminalda shu virtual muhit va `.env` bilan:

```sh
python -m app.worker
```

`uvicorn main:app` ham ishlaydi. Jadval va xabar vazifalari API jarayonida yashirin
ishga tushmaydi; worker alohida jarayon bo'lishi kerak.

## API'dan foydalanish

`POST /api/v1/auth/login`:

```json
{"username":"admin","password":"siz-tanlagan-parol"}
```

Natijadagi `access_token`ni Swagger'dagi **Authorize** tugmasiga kiriting yoki
`Authorization: Bearer <token>` header'ini yuboring. Access token 15 daqiqa,
refresh token 7 kun amal qiladi. `POST /auth/refresh` JSON tanasi:
`{"refresh_token":"..."}`. Har refresh bir martalik: yangisini saqlash kerak.

To'lov va refund so'rovlarida **`Idempotency-Key`** header'i majburiy, 8–100 belgi.
Bitta mantiqiy amalni qayta yuborishda bir xil kalitni ishlating. Shu kalit bilan
boshqa ma'lumot yuborilsa `409 idempotency_conflict` qaytadi.

```http
POST /api/v1/payments
Authorization: Bearer <token>
Idempotency-Key: payment-client-operation-001
Content-Type: application/json

{
  "student_id": 1,
  "group_id": 1,
  "amount": 400000,
  "method": "cash",
  "period": "2026-10",
  "note": "Oktabr uchun"
}
```

Ro'yxatlarda `page=1&size=20`; maksimal `size=100`. Natija:
`{"items":[],"total":0,"page":1,"size":20}`. Xatolar:
`{"detail":"...","code":"..."}`; `422` javobida maydonlar ham ko'rsatiladi.
Mavjud bo'lmagan ID — `404`, huquq yetishmasligi — `403`, biznes ziddiyati — `409`.

To'liq endpointlar va so'rov turlari Swagger'da. ZIP'dan olingan asl talablar:
[docs/original-api-spec.md](docs/original-api-spec.md).

## Ruxsatlar va xavfsizlik

| Amal | admin | manager | teacher |
|---|---|---|---|
| Xodimlar, sozlamalar, audit, o'qituvchi yuklamasi | Ha | Yo'q | Yo'q |
| O'quvchi, lid, kurs, guruh boshqaruvi | Ha | Ha | Faqat o'z guruhlari/o'quvchilarini ko'rish |
| Kurslar ro'yxati | Ha | Ha | Ha |
| Davomat | Ha | Ha | Faqat o'z guruhlari |
| To'lov, refund, qarz, dashboard, boshqa hisobotlar | Ha | Ha | Yo'q |
| Telegram xabarlari | Ha | Ha | Yo'q |

Parollar Argon2 bilan xeshlanadi. JWT algoritmi HS256 bilan qat'iy belgilangan,
issuer/audience/expiry tekshiriladi. Refresh tokenlarning faqat SHA-256 xeshi bazaga
yoziladi. Parol/rol o'zgarishi yoki bloklash token versiyasi orqali sessiyalarni
bekor qiladi. Logout faqat berilgan refresh sessiyani bekor qiladi; access token
o'zining qisqa muddati oxirigacha amal qiladi. Login uchun bazada 15 daqiqalik
10 ta noto'g'ri urinish chegarasi bor; u API worker'lari orasida umumiy.

Xodim o'zini o'chira olmaydi yoki rolini o'zgartira olmaydi. Faol guruhi bor
o'qituvchi bloklanmaydi. To'lov/refund ma'lumotlarini yangilash/o'chirish endpointi
yo'q; qaytarish alohida ledger yozuvi. Auditga parol va tokenlar yozilmaydi.

## Biznes qoidalari

- Pul **butun so'm**: float, string, bool va manfiy pul qabul qilinmaydi.
  To'lov musbat, kurs narxi nol bo'lishi mumkin. Maksimal so'rov summasi `10^12` UZS.
- Bitta markaz uchun mo'ljallangan. Filial/tenant ajratish, ish haqi va onlayn
  to'lov provayderlari ushbu ZIP talablari doirasiga kirmagan.
- Vaqt zonasi `Asia/Tashkent`; audit va operatsiya vaqtlari UTC'da saqlanadi.
- Oylik narx kalendar kunlariga mutanosib hisoblanadi. Qabul kuni hisobga kiradi,
  guruhdan chiqish kuni kirmaydi. Guruh tugash kuni kiradi. Muzlatishning ikki
  chegara kuni ham to'lovdan chiqariladi.
- Chegirma kunma-kun qo'llanadi. Summa turi oylik narxdan chegirma, foiz turi
  narxning foizi. Yakunda bir marta butun so'mga half-up yaxlitlanadi. Manfiy
  hisob chiqmaydi. Bitta o'quvchining chegirma davrlari kesishmaydi.
- Bir o'quvchi/guruh/oy uchun faqat bitta hisob. Yaratilgan hisob **snapshot**:
  qayta generatsiya narxni o'zgartirmaydi. Hisoblangan oyga muzlatish, yangi chegirma
  yoki chiqish sanasini orqaga kiritish `409 period_already_billed` beradi.
  Muzlatish/chegirma rejasini hisob yaratilishidan oldin kiriting; kelajak oylariga
  oldindan rejalash mumkin. Kredit-nota bilan eski hisobni qayta hisoblash hali yo'q.
- Worker har kuni joriy oyning yetishmayotgan hisoblarini va keyingi 7 kunlik darslarni
  yaratadi. Qo'lda `POST /invoices/generate` va `POST /lessons/generate` ham mavjud.
- Balans o'quvchi bo'yicha umumiy: `to'lov − refund − hisoblar`. Musbat qiymat avans,
  manfiy qiymat qarz. Qarzdorlik yoshi net to'lovlarni eng eski hisobdan boshlab
  qoplash asosida aniqlanadi. Guruh/oy bo'yicha to'lov teglar saqlanadi.
- O'quvchi arxivlanishidan oldin guruhlaridan chiqariladi; faol o'quvchisi bor guruh
  va faol guruhi bor kurs arxivlanmaydi. Tarix saqlanadi. Ayni guruhga takroriy
  qabul ochilmaydi; yangi o'qish davri uchun yangi guruh yaratiladi.
  Kelajakdagi chiqish sanasi yetguncha o'quvchi guruhda ko'rinadi va joyni band
  qiladi. Arxivlangan o'quvchining oldingi qarzini to'lashga ruxsat bor.
- Ishlatilgan guruhning jadval/kurs/o'qituvchi maydonlarini almashtirish bloklangan.
  Darsni alohida ko'chirish/bekor qilish mumkin; boshqa kurs yoki o'qituvchiga o'tish
  uchun yangi guruh ochiladi. Yaratilgan dars ko'chirilsa, worker eski slotni qayta
  yaratmaydi. Davomati yozilgan dars ko'chirilmaydi.
- Davomat PUT butun dars ro'yxatini talab qiladi: aynan dars kunida qabul qilingan,
  chiqmagan va muzlatilmagan o'quvchilar. Takroriy ID, begona o'quvchi, kelajak yoki
  bekor qilingan dars qabul qilinmaydi. Foizda `present`/`late` kelgan deb olinadi,
  `absent`/`excused` kelmagan deb olinadi; yozuvsiz darslar maxrajga kirmaydi.
- JSON chek mavjud; XLSX eksportda foydalanuvchi matnidan formula-injection
  himoyasi bor. Eksport maksimal 10 000 yozuv, kattaroq natijani sana bilan toraytiring.

## Telegram

`.env`da `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` (`@`siz),
`TELEGRAM_WEBHOOK_SECRET`ni belgilang. Telegram `setWebhook` orqali HTTPS
`/api/v1/telegram/webhook` manzilini va ayni `secret_token`ni ro'yxatdan o'tkazing.
API bot yaratmaydi yoki webhook'ni avtomatik tashqariga ro'yxatdan o'tkazmaydi.

`POST /students/{id}/telegram-link` 30 daqiqalik, bir martalik `/start` havola
yaratadi. Yangi havola eskilarini bekor qiladi; faqat private chat ulanadi. Havolani
tegishli ota-onaga bering — havola egasi o'quvchi xabarlarini olish huquqini oladi.
Bir o'quvchi uchun bitta Telegram chat saqlanadi.

Xabarlar bazadagi outbox'ga yoziladi. Token bo'lmasa yoki ota-ona ulanmagan bo'lsa
`pending` turadi. Worker to'lov tasdig'i, kelmaganlik, muddatdan 3 kun oldingi va
haftalik qarz eslatmalarini jo'natadi. Xatolar eksponensial kechikish bilan 5 marta
uriniladi, keyin `failed`; bot tokeni xato matniga kiritilmaydi. Worker logini va
`GET /notifications`ni kuzating. Dars jadvali ziddiyati loglanadi, hisoblash va
eslatmalar esa davom etadi.

Telegram transporti **at-least-once**: tashqi servis qabul qilib, worker DB commit'dan
oldin to'xtasa, xabar qayta ketishi mumkin. DB ichidagi hodisalar deduplikatsiya
qilinadi, lekin tashqi Telegram'da mutlaq exactly-once va'da qilinmaydi.

## Test va sifat tekshiruvlari

Faqat alohida, nomi `_test` bilan tugaydigan PostgreSQL bazasida test ishlating.
Fixture shu bazadagi CRM jadvallarini har testdan oldin tozalaydi. SQLite fallback yo'q.

```sh
python -m pip install -r requirements-dev.txt
# Windows PowerShell:
$env:TEST_DATABASE_URL = "postgresql+psycopg://crm:password@localhost:5432/crm_test"
# Linux: export TEST_DATABASE_URL='postgresql+psycopg://crm:password@localhost:5432/crm_test'
python -m pytest --cov=app --cov-report=term-missing --cov-report=html
python -m ruff check app tests main.py alembic
python -m ruff format --check app tests main.py alembic
```

Testlar haqiqiy PostgreSQL transaction, FK/unique constraint va row/advisory lock'larini
ishlatadi. Telegram so'rovlari `httpx.MockTransport` bilan tekshiriladi, haqiqiy
ota-onalarga xabar yuborilmaydi. Yakuniy natija: [docs/test-report.md](docs/test-report.md).

`.github/workflows/tests.yml` PostgreSQL bilan CI bajaradi. Ushbu kompyuter uchun
`scripts/verify.ps1` portable `.local/pgsql` va `.packages` orqali tekshirish yordamchisi;
boshqa kompyuterda yuqoridagi standart buyruqlar yoki CI'dan foydalaning.

## Tuzilma va xizmat ko'rsatish

- `app/api/` — bo'limlar bo'yicha FastAPI router'lar.
- `app/models.py`, `app/schemas.py` — DB va kiruvchi ma'lumot sxemalari.
- `app/services.py` — billing, jadval, ruxsat va bildirishnoma biznes qoidalari.
- `app/security.py` — JWT, refresh, parol xeshlash.
- `app/worker.py` — alohida fon jarayoni; bir nechta nusxa DB lock bilan ishlaydi.
- `alembic/versions/` — versiyalangan migratsiyalar; runtime `create_all` ishlatilmaydi.
- `tests/` — API, biznes qoidalari, concurrency va regressiya testlari.

Production'da maxfiy kalitlar, HTTPS, zaxira nusxa jadvali va monitoringni muhitga
mos sozlang. PostgreSQL `pg_dump` bilan muntazam backup oling va alohida bazada
restore'ni sinang. Migratsiyadan oldin backup oling; yangi sxema uchun
`alembic revision --autogenerate`, ko'rib chiqish, so'ng `alembic upgrade head`.
Test qamrovi barcha mumkin bo'lgan holatlar isboti emas; yuklama/penetratsion test
va real Telegram tokeni bilan yakuniy integratsion tekshiruv alohida bajariladi.

Texnik manbalar: [FastAPI JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
[SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html).
