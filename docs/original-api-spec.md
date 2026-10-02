# O'quv markaz CRM — FastAPI API hujjati

Barcha yo'llar `/api/v1` prefiksi ostida.

## Rollar

- `admin` — markaz egasi, hamma narsaga ruxsat
- `manager` — administrator (o'quvchilar, guruhlar, to'lovlar)
- `teacher` — o'qituvchi, faqat o'z guruhlarini ko'radi, to'lovlarga kira olmaydi

## Umumiy qoidalar

- Ro'yxatlar sahifalanadi: `?page=1&size=20`. Javob: `{"items": [...], "total": 120, "page": 1}`
- Xatolar bir xil formatda: `{"detail": "Bunday o'quvchi topilmadi", "code": "student_not_found"}`
- Soft delete: o'quvchi, guruh, to'lovlar bazadan o'chirilmaydi (`is_active` yoki `deleted_at`)
- Huquqlar FastAPI `Depends` orqali rol bo'yicha tekshiriladi
- Sanalar ISO formatda (`2026-10-01`), pul butun son (so'mda), `float` ishlatilmaydi
- To'lovlar o'chirilmaydi, faqat qaytarish (refund) yoziladi

---

## 1. Autentifikatsiya

| Metod | Yo'l | Vazifasi |
|---|---|---|
| POST | `/auth/login` | login + parol, `access_token` va `refresh_token` qaytaradi |
| POST | `/auth/refresh` | yangi access token olish |
| GET | `/auth/me` | joriy foydalanuvchi ma'lumoti va roli |
| POST | `/auth/change-password` | parolni almashtirish |

## 2. Xodimlar (faqat admin)

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/users` | xodimlar ro'yxati |
| POST | `/users` | yangi o'qituvchi/menejer qo'shish |
| PATCH | `/users/{id}` | tahrirlash, rolni o'zgartirish |
| DELETE | `/users/{id}` | o'chirish (aslida `is_active=false`) |

## 3. O'quvchilar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/students` | ro'yxat, filtr: `?search=ali&status=active&group_id=3&has_debt=true&page=1&size=20` |
| POST | `/students` | yangi o'quvchi |
| GET | `/students/{id}` | to'liq profil (guruhlari, qarzi, davomat foizi) |
| PATCH | `/students/{id}` | tahrirlash |
| DELETE | `/students/{id}` | arxivga olish |
| POST | `/students/{id}/parents` | ota-ona qo'shish |
| GET | `/students/{id}/attendance` | o'quvchining davomat tarixi |
| GET | `/students/{id}/payments` | o'quvchining to'lovlar tarixi |
| GET | `/students/{id}/balance` | joriy balans |
| POST | `/students/{id}/discounts` | chegirma berish (foiz yoki summa, muddati) |

`POST /students` namunasi:

```json
{
  "full_name": "Aliyev Jasur",
  "birth_date": "2012-05-14",
  "phone": "+998901234567",
  "parent_name": "Aliyev Botir",
  "parent_phone": "+998931112233",
  "address": "Andijon sh.",
  "note": "Do'stining tavsiyasi bilan keldi"
}
```

## 4. Lidlar (hali yozilmagan, qiziqqan odamlar)

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/leads` | ro'yxat, `?status=new/contacted/trial/enrolled/lost` |
| POST | `/leads` | yangi lid (ism, telefon, qiziqqan kurs, manba: Instagram, Telegram, tanish) |
| PATCH | `/leads/{id}` | statusni o'zgartirish, izoh qo'shish |
| POST | `/leads/{id}/convert` | lidni o'quvchiga aylantirish va guruhga qo'shish |

## 5. Kurslar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/courses` | kurslar ro'yxati |
| POST | `/courses` | yangi kurs (nomi, oylik narx, davomiyligi) |
| PATCH | `/courses/{id}` | narx va nomini o'zgartirish |
| DELETE | `/courses/{id}` | arxivlash |

## 6. Guruhlar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/groups` | ro'yxat, `?teacher_id=2&course_id=1&status=active` |
| POST | `/groups` | guruh ochish (kurs, o'qituvchi, dars kunlari, vaqti, xona) |
| GET | `/groups/{id}` | guruh tafsiloti |
| PATCH | `/groups/{id}` | tahrirlash |
| GET | `/groups/{id}/students` | guruhdagi o'quvchilar |
| POST | `/groups/{id}/students` | o'quvchini guruhga qo'shish |
| DELETE | `/groups/{id}/students/{student_id}` | guruhdan chiqarish |
| POST | `/groups/{id}/freeze/{student_id}` | o'quvchini vaqtincha muzlatish (to'lov hisoblanmaydi) |

`POST /groups` namunasi:

```json
{
  "name": "Python-12",
  "course_id": 1,
  "teacher_id": 2,
  "days": ["mon", "wed", "fri"],
  "start_time": "15:00",
  "end_time": "16:30",
  "room": "2-xona",
  "start_date": "2026-10-05"
}
```

## 7. Darslar jadvali

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/lessons` | `?date=2026-10-01&teacher_id=2` bugungi darslar |
| GET | `/lessons/{id}` | dars tafsiloti |
| POST | `/lessons` | qo'shimcha dars qo'yish |
| PATCH | `/lessons/{id}` | ko'chirish yoki bekor qilish |

Darslar guruh jadvalidan avtomatik yaratiladi (har kuni yoki hafta boshida fon vazifa orqali).

## 8. Davomat

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/lessons/{id}/attendance` | shu darsning davomat varaqasi |
| PUT | `/lessons/{id}/attendance` | butun guruh davomatini bir so'rovda saqlash |
| GET | `/groups/{id}/attendance` | `?month=2026-10` oylik jadval |

`PUT /lessons/{id}/attendance` namunasi:

```json
{
  "records": [
    {"student_id": 12, "status": "present"},
    {"student_id": 15, "status": "absent", "reason": "kasal"},
    {"student_id": 18, "status": "late"}
  ]
}
```

Statuslar: `present`, `absent`, `late`, `excused`. Saqlangach, kelmagan o'quvchining ota-onasiga Telegram xabar ketishi mumkin.

## 9. To'lovlar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/payments` | `?student_id=&from=&to=&method=cash/card/transfer` |
| POST | `/payments` | to'lov qabul qilish |
| GET | `/payments/{id}` | to'lov tafsiloti |
| POST | `/payments/{id}/refund` | to'lovni qaytarish |
| GET | `/payments/{id}/receipt` | chek (PDF yoki JSON) |
| GET | `/debtors` | qarzdorlar ro'yxati (qarz summasi, necha kun kechikkani) |

`POST /payments` namunasi:

```json
{
  "student_id": 12,
  "group_id": 3,
  "amount": 400000,
  "method": "cash",
  "period": "2026-10",
  "note": "Oktabr oyi uchun"
}
```

## 10. Hisoblar (invoices)

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/invoices` | oylik hisoblar (kim qancha to'lashi kerak) |
| POST | `/invoices/generate` | oy boshida barcha faol o'quvchilarga hisob yaratish |

## 11. Telegram bot va eslatmalar

| Metod | Yo'l | Vazifasi |
|---|---|---|
| POST | `/telegram/webhook` | Telegram'dan keladigan xabarlar |
| POST | `/students/{id}/telegram-link` | ota-onaga ulash havolasi/kodi yaratish |
| POST | `/notifications/send` | qo'lda xabar yuborish (guruhga yoki bitta o'quvchiga) |
| GET | `/notifications` | yuborilgan xabarlar tarixi va holati |
| GET | `/notifications/templates` | xabar matn shablonlarini olish |
| PUT | `/notifications/templates` | shablonlarni saqlash |

Avtomatik ketadigan xabarlar (fon vazifa: APScheduler yoki Celery):

- to'lov muddatidan 3 kun oldin eslatma
- qarz bo'lsa, har hafta eslatma
- o'quvchi darsga kelmasa, shu kuni ota-onaga xabar
- to'lov qabul qilinganda tasdiq xabari

## 12. Hisobotlar va dashboard

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/dashboard` | faol o'quvchilar, bugungi darslar, oylik tushum, jami qarz |
| GET | `/reports/income` | `?from=&to=` kunlik/oylik tushum |
| GET | `/reports/attendance` | guruhlar bo'yicha o'rtacha davomat |
| GET | `/reports/debts` | qarzlar bo'yicha hisobot |
| GET | `/reports/teachers` | o'qituvchilar yuklamasi |
| GET | `/reports/export` | `?type=payments&format=xlsx` Excel'ga yuklab olish |

## 13. Sozlamalar va tizim

| Metod | Yo'l | Vazifasi |
|---|---|---|
| GET | `/settings` | markaz nomi, telefon, to'lov kuni, Telegram bot holati |
| PUT | `/settings` | sozlamalarni saqlash |
| GET | `/audit-log` | kim nimani o'zgartirgani |
| GET | `/version` | ilova versiyasi (PyQt `.exe` yangilanishini tekshirish uchun) |

---

## Rollar bo'yicha ruxsatlar

| Bo'lim | admin | manager | teacher |
|---|---|---|---|
| Xodimlar | + | - | - |
| O'quvchilar | + | + | faqat o'z guruhidagilar (ko'rish) |
| Lidlar | + | + | - |
| Kurslar | + | + | ko'rish |
| Guruhlar | + | + | faqat o'zinikini ko'rish |
| Davomat | + | + | faqat o'z guruhlari |
| To'lovlar, qarzdorlar | + | + | - |
| Telegram xabarlar | + | + | - |
| Hisobotlar | + | qisman | - |
| Sozlamalar, audit-log | + | - | - |

## Yozish tartibi (tavsiya)

1. `auth`, `users`
2. `students`, `courses`, `groups`
3. `lessons`, `attendance`
4. `payments`, `debtors`, `invoices`
5. `telegram`, `notifications`
6. `dashboard`, `reports`, `settings`, `audit-log`
