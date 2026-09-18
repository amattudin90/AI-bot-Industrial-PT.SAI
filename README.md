# Factory AI Operations System — V10 Unified

## Konsep
Satu **AI Core** dipakai oleh dua interface:
- `app.py` → Streamlit / Control Tower
- `bot.py` → Telegram Agent

Keduanya berbagi:
- `core/data_engine.py` → V1/V2 Excel parser
- `core/ai_engine.py` → Gemini reasoning
- `core/database.py` → history + activity log
- `core/workflow.py` → parser action
- `integrations/google_services.py` → Drive / Sheets / Calendar

## Workflow utama
User → Interface → AI Core → Factory Data → Deterministic Metrics → AI Reasoning → Workflow Action → Audit Log

## Instalasi
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` menjadi `.env`, lalu isi API key/token.

Letakkan Excel di folder `data/`:
- `Capa analysis machine per procesV1.xlsx`
- `Capa analysis machine per procesV2.xlsx`

## Jalankan
Terminal 1:
```bash
python -m streamlit run app.py
```

Terminal 2:
```bash
python bot.py
```

Atau Windows:
- `run_streamlit.bat`
- `run_telegram.bat`

## Google OAuth
Untuk Drive/Sheets/Calendar:
1. Letakkan `client_secret.json` di root project.
2. Jalankan workflow Google pertama kali dari bot.
3. Browser OAuth akan membuat `token.json`.
4. Jangan upload `.env`, `client_secret.json`, atau `token.json` ke Git/public server.

## Catatan penting
Versi ini sengaja memisahkan **AI reasoning** dari **workflow execution**.
Calendar memakai draft → user CONFIRM → baru event dibuat.
Ini mencegah AI membuat jadwal secara tidak sengaja.

## Next development
1. Deterministic capacity engine per model/process.
2. Bottleneck ranking.
3. What-if simulation.
4. Telegram inline dashboard.
5. Persistent factory master database.
6. Role-based access.
7. KPI / OEE / downtime integration.
8. Automatic daily management report.

## Validasi awal
Seluruh file Python pada paket ini sudah melewati **syntax/compile check**.
Runtime validation tetap perlu dilakukan di PC yang memiliki API key, Telegram token,
Google credentials, dan dependency lengkap.
