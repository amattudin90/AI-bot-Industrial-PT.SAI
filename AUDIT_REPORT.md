# Factory AI Audit & Refactor Report

Tanggal pemeriksaan: 12 Oktober 2026

## Yang diubah

- `bot.py` diringkas menjadi entry point 7 baris dan tetap memakai nama/path lama agar launcher tetap kompatibel.
- Handler Telegram dipisah berdasarkan tanggung jawab ke `bot_app/handlers/skills.py`, `finance.py`, `tasks.py`, dan `messages.py`.
- Registrasi command, callback, job baterai, dan startup dipindah ke `bot_app/application.py`.
- Konfigurasi, prompt, integrasi, dan state bersama dipusatkan di `bot_app/context.py`.
- `requirements-bot.txt` dilengkapi dengan dependensi yang dipakai oleh bot, MT5, dan skill sistem; `requirements.txt` tetap mencakup Streamlit.
- Ditambahkan `.env.example`, panduan setup, tes offline, dan demo skill yang tidak mengubah state produksi atau mengunci laptop.
- Skrip pemeliharaan dipindah ke `tools/` dan menggunakan path proyek yang lebih stabil.
- Launcher `.bat` menggunakan lokasi folder proyek, bukan path akun Windows yang ditulis permanen.

## Yang dibersihkan dari paket distribusi

- `.venv/`, `__pycache__/`, file `.pyc`, log lama, dan gambar sementara Telegram.
- `client_secret.json` tidak disertakan; salin kredensial OAuth milik sendiri secara lokal.
- `core/workflow.py` dan `integrations/google_services.py` tidak memiliki referensi pemakaian di source project yang diperiksa dan menduplikasi sebagian fungsi yang masih diimplementasikan di tempat lain. Keduanya dihilangkan dari paket bersih.
- File workbook, database lokal, state skill/radar, dan jurnal trading dipertahankan karena merupakan data proyek atau state runtime, bukan sekadar cache.

## Pemeriksaan yang lulus

- Semua file Python lolos parsing/kompilasi (`compileall`).
- AST dari 42 fungsi asli di `bot.py`, termasuk `main`, identik dengan AST fungsi hasil pemindahan. Artinya isi badan fungsi tidak diubah saat refactor.
- Dua tes offline `SkillManager` lulus: dispatch ketika skill nonaktif/aktif, persistensi status, dan respons skill yang tidak dikenal.
- Demo baterai untuk nilai 8%, 50%, dan 99% lulus. Uji laptop hanya memastikan aksi tertahan karena konfirmasi tidak diberikan; laptop tidak dikunci.
- Pemeriksaan referensi global statis untuk modul handler hasil refactor tidak menemukan nama global yang hilang.

## Batas pengujian

Bot belum dijalankan terhadap Telegram, Google API, dan MT5 nyata dari lingkungan audit ini. Dependensi eksternal Telegram tidak terpasang di lingkungan pemeriksaan, dan integrasi nyata membutuhkan token, kredensial, Windows, serta terminal MT5. Karena itu, hasil ini adalah refactor dengan pemeriksaan statis dan tes offline, bukan jaminan bahwa seluruh layanan eksternal sudah lolos uji langsung.

## Hal yang perlu ditinjau pada tahap berikutnya

1. `TELEGRAM_ALLOWED_USERS` kosong membuat handler umum bot mengizinkan semua pengguna. Isi ID Telegram yang benar di `.env`; trading memiliki pemeriksaan allowlist tersendiri.
2. `core/config.py` menetapkan nama default `Capa analysis machine per procesV1.xlsx` dan `Capa analysis machine per procesV2.xlsx`, sedangkan ZIP yang diaudit berisi workbook bernama lain. UI `app.py` sengaja tidak diubah sesuai ruang lingkup, jadi mapping workbook perlu diverifikasi sebelum mengaktifkan kembali dashboard.
3. Uji integrasi end-to-end sebelum mengganti folder produksi, khususnya Google OAuth, transaksi dan `/undo`, tombol task/habit, notifikasi baterai, konfirmasi order MT5, dan shutdown/restart radar.
