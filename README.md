# 🎙️ Podcast Məlumatlarının Aqreqasiyası və RESTful API Platforması

Müxtəlif beynəlxalq çart platformalarından (Spotify və Podchaser) podkast reytinqlərini avtomatlaşdırılmış şəkildə toplayan, rəsmi xarici API-lər (Apple Podcasts / iTunes) vasitəsilə metadata və reytinqlərlə zənginləşdirən, RSS axınlarını yüksək performans və yaddaş təhlükəsizliyi ilə sinxronlaşdıran və analitik RESTful API təqdim edən backend platforması.

---

## 🚀 Əsas Funksionallıqlar və Arxitektura

* **Avtomatlaşdırılmış Çoxplatformalı Scraping:**
  * **Spotify Podcast Charts:** Canlı reytinqlər, təsvirlər və platforma identifikatorları toplanır.
  * **Podchaser / Apple Charts:** Müxtəlif kateqoriyalar və qlobal bazarlar üzrə reytinqlər çəkilir, şəbəkə xətalarında (502/503/timeout) avtomatik təkrar cəhd (retry) məntiqi tətbiq olunur.
* **Qlobal Ölkə və Kateqoriya Kəşfi (Discovery):**
  * **175 Dəstəklənən Ölkə:** Apple və Spotify platformalarının dəstəklədiyi bütün 175 rəsmi bazar bazaya yazılır və hər ölkə üzrə platforma dəstəyi ayrıca izlənilir.
  * **110+ İyerarxik Çart Kateqoriyası:** Apple iTunes rəsmi taksonomiyasından dinamik oxunaraq Ana və Alt kateqoriya (Parent-Child) formatında sıralama nömrələri ilə saxlanılır.
  * **Top Epizod Dəstəyi (Top Episodes):** `top-episodes` çartı vasitəsilə fərdi epizodların reytinqləri saxlanılır və API-də birbaşa epizod obyekti ilə əlaqələndirilir.
* **Verilənlər Bazası Arxitekturası və PostgreSQL Range Partitioning:**
  * **Deklarativ Cədvəl Partisyalaşdırılması:** `ChartRanking` cədvəli `date` sütununa əsasən illik hissələrə (`RANGE (date)`, 2024–2030 və `DEFAULT`) bölünüb. Bu, milyonlarla reytinq qeydi olduqda belə həm oxuma, həm də yazma sürətini maksimum səviyyədə saxlayır.
  * **Kompozit B-Tree İndeksləri:** `(category, country, date, rank)`, `(country, date)` və `(date, source)` sahələri üzrə xüsusi indekslər vasitəsilə cədvəl skan edilmədən birbaşa indekslər üzərindən ən sürətli cavab təmin edilir.
* **Davamlı RSS Streaming və Bulk UPSERT:**
  * **Hissə-Hissə Axın (`httpx.stream`):** Böyük həcmli RSS faylları bütöv şəkildə RAM-a yüklənmədən hissələrlə oxunur (yaddaş sızması və OOM xətalarının qarşısı 100% alınır).
  * **Kütləvi UPSERT (`bulk_create(..., update_conflicts=True)`):** Epizodlar `(podcast, guid)` unikal açarı üzrə 500-lük partiyalar halında bazaya yazılır və ya mövcud olduqda yenilənir.
  * **Şəbəkə Davamlılığı:** Dinamik modern masaüstü `User-Agent` və `Sec-Ch-Ua` başlıqlarının rotasiyası, 25 saniyəlik timeout, Celery exponential backoff və jitter mexanizmi.
* **Yüksək Performanslı Django Admin:**
  * **`LargeTablePaginator`:** Çoxmilyonluq `Episode` və `ChartRanking` cədvəllərində ləng `SELECT COUNT(*)` sorğusunu aradan qaldırır, PostgreSQL-in `pg_class` statistikasından ani təxmini say əldə edir.
  * **`PaginatedTabularInline`:** Podkast admin səhifəsində minlərlə epizod və reytinq tarixçəsi brauzeri dondurmadan dinamik səhifələnmə (pagination) və naviqasiya ilə göstərilir.
* **Arxa Plan və Dövri Tapşırıqlar (Celery + Redis):**
  * Çəkim, zənginləşdirmə və epizod sinxronizasiyası asinxron növbələrə bölünür.
  * **Celery Beat:** Hər gecə saat 00:00-da (UTC) gündəlik scraping avtomatik başladılır, həftəlik ölkə və kateqoriya yenilənmələri icra edilir.
* **İnteraktiv API Sənədləşməsi (OpenAPI 3.0):**
  * `drf-spectacular` ilə Swagger UI və ReDoc inteqrasiyası.

---

## 🛠️ Texnoloji Stek

| Sahə | Texnologiya |
| :--- | :--- |
| **Backend Çərçivəsi** | Python 3.12, Django 5.2, Django REST Framework |
| **Verilənlər Bazası** | PostgreSQL 16 (Range Partitioning ilə) |
| **Arxa Plan və Növbə** | Celery 5.4, Celery Beat, Redis 7 |
| **Scraping və Şəbəkə** | HTTPX, Feedparser, BeautifulSoup4 |
| **API Sənədləşməsi** | drf-spectacular (OpenAPI 3.0, Swagger UI, ReDoc) |
| **Konteynerləşdirmə** | Docker, Docker Compose |

---

## 📂 Layihə Strukturu

```text
podcast-api/
├── apps/
│   ├── common/                         # Ümumi köməkçi modullar, pagination, baza modelləri
│   │   ├── models.py                   # TimeStampedModel abstract base
│   │   ├── pagination.py               # Standart və offset-based pagination
│   │   └── utils.py                    # Təmiz HTML və mətn emalı funksiyaları
│   │
│   └── podcasts/                       # Podkast domen modulu
│       ├── fixtures/                   # Ehtiyat məlumatlar (apple_storefronts.json)
│       ├── management/commands/        # CLI idarəetmə əmrləri
│       │   ├── seed_system_data.py     # 175 ölkə və 110+ kateqoriyanı bazaya doldurur
│       │   ├── run_scraper.py          # Çart çəkimini və inteqrasiyasını başladır
│       │   ├── sync_episodes.py        # RSS epizodlarını yüksək sürətlə sinxronlaşdırır
│       │   └── enrich_ratings.py       # Apple/Spotify-dan reytinqləri zənginləşdirir
│       ├── migrations/                 # PostgreSQL miqrasiyaları (o cümlədən partisyalar)
│       ├── models/                     # Data modelləri (Category, Country, ChartCategory, Podcast, Episode, ChartRanking, PodcastRating)
│       ├── serializers/                # DRF serializer-ləri (Podcast, Chart, Episode, Category)
│       ├── services/                   # Əsas biznes məntiqi və servis qatı
│       │   ├── spotify_scraper.py      # Spotify çart məlumatlarının çəkilməsi
│       │   ├── podchaser_scraper.py    # Podchaser/Apple çart məlumatlarının çəkilməsi
│       │   ├── country_discovery.py    # Qlobal ölkələrin dinamik kəşfi servisi
│       │   ├── category_discovery.py   # iTunes kateqoriya taksonomiyası sinxronizatoru
│       │   ├── enricher.py             # Metadata və platforma reytinqlərini zənginləşdirici
│       │   ├── rss_fetcher.py          # Yaddaş təhlükəsizliyi ilə axınlı RSS oxucu və bulk UPSERT
│       │   ├── http_client.py          # Brauzer başlıqlarının rotasiyası və bot müdafiəsi
│       │   └── pipeline.py             # Əsas inteqrasiya boru kəməri
│       ├── tasks/                      # Celery arxa plan tapşırıqları
│       │   ├── scraping.py             # Çart çəkimi və kəşf tapşırıqları
│       │   ├── enrichment.py           # Metadata və reytinq zənginləşdirmə tapşırıqları
│       │   └── episodes.py             # Epizod sinxronizasiya tapşırıqları
│       ├── views/                      # Süzgəcləmə və səhifələmə ilə API View-ları
│       ├── admin.py                    # Optimallaşdırılmış Django Admin paneli
│       ├── tests.py                    # Hərtərəfli vahid testləri (38 test)
│       └── urls.py                     # API marşrutları (həm '/' həm də slashesiz)
│
├── config/                             # Əsas layihə konfiqurasiyası
│   ├── settings.py                     # Parametrlər (PostgreSQL, Celery, DRF, Swagger)
│   ├── urls.py                         # Kök URL routing
│   └── celery.py                       # Celery tətbiqi və beat qrafikləri
│
├── docker-compose.yml                  # PostgreSQL, Redis, Web, Celery Worker, Beat və Flower
├── Dockerfile                          # Çoxmərhələli Docker obrazı
├── requirements.txt                    # Python asılılıqları
├── manage.py                           # Django CLI
└── README.md
```

---

## 🚀 Quraşdırma və İşə Salma

### Metod 1: Docker Compose ilə (Tövsiyə olunan)

Bütün servisləri (PostgreSQL, Redis, Web Server, Celery Worker, Celery Beat, Flower) tək əmrlə işə salın:

```bash
docker compose up --build -d
```

Konteynerlərin statusunu yoxlayın:
```bash
docker compose ps
```

İlkin ölkə və kateqoriya məlumatlarını bazaya yükləyin:
```bash
docker compose exec web python manage.py seed_system_data
```

---

### Metod 2: Lokal Mühitdə (Virtualenv ilə)

1. **Virtual mühiti yaradın və aktivləşdirin:**
   ```bash
   python -m venv venv
   # Windows:
   .\venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

2. **Kitabxanaları quraşdırın:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ətraf mühit dəyişənlərini (`.env`) təyin edin:**
   ```env
   DEBUG=True
   SECRET_KEY=your-secret-key
   ALLOWED_HOSTS=localhost,127.0.0.1
   DB_ENGINE=postgresql
   DB_NAME=podcast_db
   DB_USER=podcast_user
   DB_PASSWORD=podcast_password
   DB_HOST=localhost
   DB_PORT=5432
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/0
   ```

4. **Verilənlər bazası miqrasiyalarını tətbiq edin:**
   ```bash
   python manage.py migrate
   ```

5. **İlkin sistem məlumatlarını yükləyin (175 ölkə və 110+ kateqoriya):**
   ```bash
   python manage.py seed_system_data
   ```

6. **Serveri başladın:**
   ```bash
   python manage.py runserver
   ```

---

## ⚙️ İdarəetmə CLI Əmrləri (Management Commands)

### 1. `seed_system_data`
175 dəstəklənən ölkəni və 110+ iyerarxik çart kateqoriyasını Apple/Spotify taksonomiyası üzrə bazaya yükləyir:
```bash
python manage.py seed_system_data
```

### 2. `run_scraper`
Müəyyən edilmiş ölkələr və kateqoriyalar üzrə podkast çartlarını çəkir və zənginləşdirir:
```bash
python manage.py run_scraper --country us --category top-podcasts --limit 20 --episodes-limit 10
```
Parametrlər:
* `--countries`: Vergüllə ayrılmış ölkə kodları (default: `us,gb,ca,de`).
* `--country`: Tək ölkə kodu (məs: `us`, `az`, `gb`).
* `--all-countries`: Bazadakı bütün aktiv 175 ölkə üzrə çəkimi icra et.
* `--categories`: Vergüllə ayrılmış kateqoriya slug-ları.
* `--category`: Tək hədəf kateqoriya slug-ı (məs: `top-podcasts`, `top-episodes`, `comedy`, `news`).
* `--all-categories`: Bazadakı bütün aktiv çart kateqoriyaları üzrə çəkimi icra et.
* `--limit`: Hər mənbədən çəkiləcək podkast sayı (default: `20`).
* `--episodes-limit`: Top neçə podkastın RSS epizodları sinxronlaşdırılsın (default: hamısı).

### 3. `sync_episodes`
Feed URL-i olan podkastların epizodlarını yüksək performansla (asinxron və ya sinxron) yeniləyir:
```bash
python manage.py sync_episodes --top 10 --max-episodes 15
```

### 4. `enrich_ratings`
Bazada reytinqi çatışmayan podkastların reytinq və səs saylarını Apple Podcasts-dan çəkərək tamamlayır:
```bash
python manage.py enrich_ratings --limit 50
```

---

## 📡 RESTful API Uç Nöqtələri (Endpoints)

Bütün endpoint-lər `/api/v1/` prefiksi altında təqdim olunur və həm `/` ilə, həm də slashesiz (məs: `/api/v1/charts` və `/api/v1/charts/`) 200 OK ilə cavab verir.

### 1. Dəstəklənən Ölkələr API
* **Endpoint:** `GET /api/v1/countries/`
* **Süzgəcləmə və Axtarış:**
  * `?platform=spotify` / `?platform=apple` — Platforma dəstəyinə görə süzgəcləmə.
  * `?is_active=true` — Yalnız aktiv ölkələr.
  * `?search=azerbaijan` — Ölkə adı və ya kodu üzrə axtarış.
  * `?refresh=true` — Platformalardan ən son siyahını arxa planda yeniləmək.

### 2. Çart Kateqoriyaları API
* **Endpoint:** `GET /api/v1/charts/categories/`
* **Süzgəcləmə və Axtarış:**
  * `?platform=spotify` / `?platform=apple` / `?platform=all` — Platforma uyğunluğuna görə.
  * `?parent=true` — Yalnız əsas (ana) kateqoriyalar.
  * `?search=comedy` — Kateqoriya adı və ya slug-ı üzrə axtarış.

### 3. Reytinq Çartları API (Charts)
* **Endpoint:** `GET /api/v1/charts/`
* **Parametrlər:**
  * `?country=us` — ISO-2 ölkə kodu (default: `us`).
  * `?category=top-podcasts` və ya `?category=top-episodes` — Çart növü.
  * `?source=spotify` / `?source=podchaser` — Mənbə platforması.
  * `?date=2026-09-08` — Konkret tarixi gün (təyin olunmadıqda avtomatik ən son gün verilir).
  * `?page=1` — Səhifələnmə.

### 4. Podkastlar Kataloqu API
* **Endpoint:** `GET /api/v1/podcasts/`
* **Parametrlər:**
  * `?search=huberman` — Başlıq, müəllif və təsvir üzrə axtarış.
  * `?category=health-fitness` — Kateqoriyaya görə süzgəcləmə.
  * `?source=spotify` — Çarta düşdüyü platformaya görə.
  * `?min_rating=4.5` — Minimum reytinq balına görə.
  * `?rating_source=spotify` / `?rating_source=apple` — Konkret platforma reytinqinə görə.
  * `?ordering=-rating` — Reytinqə görə sıralama (reytinqsizlər sonda).

### 5. Podkast Detalı API
* **Endpoint:** `GET /api/v1/podcasts/{id}/`
* **Cavab Strukturu:** Podkastın tam metadatası, yoxlanılmış xarici platforma linkləri (Spotify, Apple), dəqiq platforma reytinq göstəriciləri (`platform_ratings`) və ən son 10 buraxılış.

### 6. Podkast Epizodları API (Offset-based)
* **Endpoint:** `GET /api/v1/podcasts/{id}/episodes/`
* **Parametrlər:**
  * `?limit=20&offset=0` — Limit və ofset əsaslı sürüşmə.
  * `?search=interview` — Epizod başlığı və ya təsviri üzrə axtarış.
  * `?ordering=-published_at` — Yayımlanma tarixinə görə sıralama.

---

## 🧪 Vahid Testlər (Unit Tests)

Layihə bütün modelləri, serializer-ləri, view-ları, servisləri, Celery tapşırıqlarını, axınlı RSS oxucusunu və admin komponentlərini əhatə edən 38 vahid testindən ibarətdir:

```bash
python manage.py test apps.podcasts
```

Yoxlama nəticəsi:
```text
Ran 38 tests in 4.859s

OK
```

---

## 📖 API Sənədləşməsi və İdarəetmə Paneli

Layihə işə düşdükdən sonra brauzerdə aşağıdakı ünvanlara daxil ola bilərsiniz:

* **Swagger UI (İnteraktiv sənədləşmə):** [http://127.0.0.1:8000/api/docs/](http://127.0.0.1:8000/api/docs/)
* **ReDoc (Alternativ sənədləşmə):** [http://127.0.0.1:8000/api/redoc/](http://127.0.0.1:8000/api/redoc/)
* **OpenAPI 3.0 Sxemi (YAML):** [http://127.0.0.1:8000/api/schema/](http://127.0.0.1:8000/api/schema/)
* **Flower (Celery İzləmə Paneli):** [http://127.0.0.1:5555/](http://127.0.0.1:5555/)
* **Django Admin Paneli:** [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

