# Factory AI

Factory AI berisi bot Telegram Shakeel, skill laptop, modul trading MT5, pencatatan keuangan/tugas/habit, dan aplikasi analisis kapasitas Streamlit. UI `app.py` dipertahankan apa adanya; refactor ini berfokus pada struktur bot dan kebersihan paket.

## Struktur utama

```text
Factory AI/
├── bot.py                    # entry point kompatibel
├── bot_app/
│   ├── context.py            # konfigurasi, state bersama, prompt, integrasi
│   ├── application.py         # registrasi handler dan startup
│   └── handlers/
│       ├── messages.py       # routing pesan teks/media
│       ├── finance.py        # transaksi, profil, tombol aksi
│       ├── tasks.py          # tugas, habit, radar, routing lokal
│       └── skills.py         # skill, baterai, lock, system status, screenshot
├── core/                     # engine data, AI, database, skill manager
├── skills/                   # satu folder per skill
├── trading_bot.py            # interface trading Telegram
├── market_scanner.py         # pemindaian pasar
├── signal_engine.py          # pembentukan sinyal
├── risk_manager.py           # pemeriksaan risiko
├── trade_executor.py         # eksekusi order dengan guardrail
├── main.py / radar.py        # proses trading/radar
├── keuangan.py / tugas.py / habit.py / penasihat.py
├── app.py                    # Streamlit, dipertahankan
├── data/                     # workbook dan data lokal yang dipakai aplikasi
├── tools/                    # utilitas pemeliharaan dan demo aman
└── requirements*.txt
```

## Setup lokal Windows

1. Gunakan folder proyek hasil ekstrak. Jangan salin folder `.venv` dari instalasi lama.
2. Buat environment baru dari terminal di folder proyek:
   ```bat
   py -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   pip install -r requirements-bot.txt
   ```
   Untuk aplikasi Streamlit juga, jalankan `pip install -r requirements.txt`.
3. Salin `.env.example` menjadi `.env`, lalu isi token Gemini, token Telegram, ID Google Sheet, dan `TELEGRAM_ALLOWED_USERS` dengan ID Telegram milikmu. Jangan membagikan `.env`.
4. Tempatkan `client_secret.json` milik proyek Google kamu di folder utama, lalu buat token jika diperlukan:
   ```bat
   python tools\generate_token.py
   ```
5. Pastikan terminal MetaTrader 5 terpasang, terbuka, dan login sebelum menguji fungsi trading.
6. Jalankan bot dengan `Start_bot.bat` atau `python bot.py`.

## Keamanan penting

- `TELEGRAM_ALLOWED_USERS` harus berisi ID Telegram yang benar. Jangan membiarkannya kosong karena akses bot umum pada konfigurasi saat ini dapat terbuka untuk semua pengguna, meskipun perintah trading memiliki allowlist terpisah.
- Perintah order MT5 tetap harus melewati konfirmasi dan validasi risiko. Uji hanya pada akun DEMO terlebih dahulu.
- `client_secret.json`, `token.json`, `.env`, dan file log tidak disertakan dalam paket bersih.
- `data/factory_ai.db`, workbook, `data/skills_state.json`, `runtime_settings.json`, `radar*.json`, dan `trade_journal.csv` dipertahankan karena berpotensi menyimpan data kerja atau state runtime.

## Refactor bot Telegram

Handler dipindahkan ke modul berdasarkan tanggung jawab. Isi badan 42 fungsi dari `bot.py` lama dipertahankan identik pada pemeriksaan AST; yang berubah adalah lokasi kode dan cara impor. `bot.py` sekarang hanya menjadi entry point kecil, sehingga kode berikutnya lebih mudah dicari dan ditambah.

## Pengujian

- Pemeriksaan sintaks: `python -m compileall -q .`
- Demo skill aman (tidak mengirim Telegram dan tidak benar-benar mengunci laptop): `python tools\skill_demo.py`
- Pengujian operasional tetap perlu dilakukan di komputer Windows dengan dependensi, kredensial, Google API, Telegram, dan MT5 yang sesuai.
