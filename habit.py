"""Otomatisasi HABIT BUILDER (tab JAN sampai DEC).

Bot hanya mencentang/menghapus centang sel habit pada hari yang dimaksud.
Baris tanggal dan daftar habit dicari otomatis dari isi tab, jadi tidak ada alamat sel yang ditulis mati.
"""
import difflib
import html
import re
from datetime import date, timedelta

from sheetutil import baca_blok, daftar_tab, kolom_huruf, kosong, norm, q, sel, tulis

TAB = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
BULAN_PENDEK = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def esc(x):
    return html.escape(str(x))


def _hari_dari(v):
    """Isi sel baris tanggal -> (hari, bulan|None, tahun|None), atau None."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if float(v).is_integer() and 1 <= v <= 31:
        return int(v), None, None
    if v > 30000:
        d = date(1899, 12, 30) + timedelta(days=int(v))
        return d.day, d.month, d.year
    return None


def _run_tanggal(pasangan):
    """Cari deretan kolom berurutan yang berisi tanggal 1, 2, 3, ... -> {hari: (kolom, bulan, tahun)}."""
    for k, (_, h) in enumerate(pasangan):
        if h[0] != 1:
            continue
        hasil = {1: (pasangan[k][0], h[1], h[2])}
        prev_col, prev_day = pasangan[k][0], 1
        for col, (d, b, y) in pasangan[k + 1:]:
            if col == prev_col + 1 and d == prev_day + 1:
                hasil[d] = (col, b, y)
                prev_col, prev_day = col, d
            else:
                break
        if len(hasil) >= 28:
            return hasil
    return None


def _cek_label(blok, tahun, bulan):
    """Kalau sel MONTH dan YEAR ada di tab, pastikan cocok dengan bulan yang dituju."""
    for row in blok[:15]:
        for j, v in enumerate(row):
            label = str(v).strip().upper()
            if label not in ("MONTH", "YEAR"):
                continue
            nilai = next((x for x in row[j + 1:] if not kosong(x)), None)
            if nilai is None:
                continue
            if label == "MONTH" and isinstance(nilai, str) and nilai.strip()[:3].lower() != TAB[bulan - 1].lower():
                raise RuntimeError(f"Tab {TAB[bulan - 1]} masih diatur ke bulan '{nilai}'. Ubah sel MONTH di tab itu ke {BULAN_PENDEK[bulan - 1]}.")
            if label == "YEAR" and str(nilai).strip() != str(tahun):
                raise RuntimeError(f"Tab {TAB[bulan - 1]} masih diatur ke tahun '{nilai}'. Ubah sel YEAR di tab itu ke {tahun}.")


def baca_habit(svc, sheet_id, tahun, bulan):
    """Baca grid habit satu bulan. Return dict: tab, hari_kolom, habits, blok."""
    tab = next((t for t in daftar_tab(svc, sheet_id) if t.strip().upper() == TAB[bulan - 1]), None)
    if not tab:
        raise RuntimeError(f"Tab {TAB[bulan - 1]} tidak ada di HABIT BUILDER.")
    blok = baca_blok(svc, sheet_id, tab, "A:AZ")
    _cek_label(blok, tahun, bulan)

    date_row, run = None, None
    for i, row in enumerate(blok):
        pasangan = [(j, h) for j, v in enumerate(row) if (h := _hari_dari(v))]
        r = _run_tanggal(pasangan) if len(pasangan) >= 28 else None
        if r:
            date_row, run = i, r
            break
    if run is None:
        raise RuntimeError(f"Baris tanggal (1, 2, 3, ...) tidak ditemukan di tab {tab}.")
    for d, (_, b, y) in run.items():
        if b is not None and (b != bulan or y != tahun):
            raise RuntimeError(f"Tab {tab} menampilkan tanggal {d}/{b}/{y}, bukan {bulan}/{tahun}. Atur sel MONTH/YEAR di tab itu.")
    hari_kolom = {d: c for d, (c, _, _) in run.items()}
    kol_awal = min(hari_kolom.values())

    habits = []
    i = date_row + 1
    while i < len(blok) and isinstance(sel(blok[i], hari_kolom[1]), bool):
        row = blok[i]
        nama = next((str(v).strip() for v in row[:kol_awal] if isinstance(v, str) and len(v.strip()) >= 2), "")
        habits.append({"baris": i + 1, "nama": nama or f"Habit {len(habits) + 1}",
                       "nilai": {d: sel(row, c) is True for d, c in hari_kolom.items()}})
        i += 1
    if not habits:
        raise RuntimeError(f"Daftar habit tidak ditemukan di tab {tab}.")
    return {"tab": tab, "tahun": tahun, "bulan": bulan, "hari_kolom": hari_kolom, "habits": habits, "blok": blok}


# ---------- menulis ----------
def cocokkan_habit(data, nama):
    kunci = norm(nama)
    if not kunci:
        raise ValueError("Nama habit kosong.")
    habits = data["habits"]
    for h in habits:
        if norm(h["nama"]) == kunci:
            return h
    sebagian = [h for h in habits if kunci in norm(h["nama"]) or norm(h["nama"]) in kunci]
    if len(sebagian) == 1:
        return sebagian[0]
    skor = sorted(((difflib.SequenceMatcher(None, kunci, norm(h["nama"])).ratio(), h) for h in habits), key=lambda x: -x[0])
    if not sebagian and skor[0][0] >= 0.7 and (len(skor) == 1 or skor[0][0] - skor[1][0] >= 0.1):
        return skor[0][1]
    raise ValueError(f"Habit '{nama}' tidak dikenali atau ambigu. Pilihan: " + ", ".join(h["nama"] for h in habits))


def catat_habit(svc, sheet_id, items, sekarang):
    """items: [{'tanggal': 'YYYY-MM-DD' (opsional), 'habit': nama, 'selesai': bool}]. Return (hasil, restore)."""
    hari_ini = sekarang.date()
    cache, updates, restore, hasil = {}, [], [], []
    for it in items:
        try:
            tgl = date.fromisoformat(str(it.get("tanggal") or hari_ini.isoformat()))
        except ValueError:
            raise ValueError(f"Format tanggal tidak valid: {it.get('tanggal')}")
        if tgl > hari_ini:
            raise ValueError("Habit tidak bisa dicatat untuk tanggal yang belum terjadi.")
        kunci = (tgl.year, tgl.month)
        if kunci not in cache:
            cache[kunci] = baca_habit(svc, sheet_id, *kunci)
        data = cache[kunci]
        h = cocokkan_habit(data, it.get("habit"))
        kol = data["hari_kolom"].get(tgl.day)
        if kol is None:
            raise ValueError(f"Tanggal {tgl.day} tidak ada di grid tab {data['tab']}.")
        rng = f"{q(data['tab'])}!{kolom_huruf(kol)}{h['baris']}"
        nilai = it.get("selesai", True) is not False
        updates.append({"range": rng, "values": [[nilai]]})
        restore.append({"range": rng, "values": [[h["nilai"].get(tgl.day, False)]]})
        hasil.append({"habit": h["nama"], "tanggal": tgl.isoformat(), "selesai": nilai})
    tulis(svc, sheet_id, updates)
    return hasil, restore


def toggle_habit(svc, sheet_id, baris, ymd):
    """Balik status satu habit pada satu hari. ymd = 'YYYYMMDD'. Return (nama, nilai_baru, restore)."""
    tgl = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8]))
    data = baca_habit(svc, sheet_id, tgl.year, tgl.month)
    h = next((x for x in data["habits"] if x["baris"] == baris), None)
    kol = data["hari_kolom"].get(tgl.day)
    if not h or kol is None:
        raise ValueError("Daftar habit berubah. Kirim /habit lagi untuk memuat ulang.")
    lama = h["nilai"].get(tgl.day, False)
    rng = f"{q(data['tab'])}!{kolom_huruf(kol)}{baris}"
    tulis(svc, sheet_id, [{"range": rng, "values": [[not lama]]}])
    return h["nama"], (not lama), [{"range": rng, "values": [[lama]]}]


# ---------- tampilan ----------
def _judul_tanggal(tgl):
    return f"{HARI_ID[tgl.weekday()]}, {tgl.day} {BULAN_PENDEK[tgl.month - 1]} {tgl.year}"


def kartu_habit(data, tgl):
    """Return (html, baris_tombol): checklist habit satu hari dengan tombol toggle."""
    ymd = tgl.strftime("%Y%m%d")
    selesai = sum(1 for h in data["habits"] if h["nilai"].get(tgl.day, False))
    total = len(data["habits"])
    L = [f"<b>HABIT</b> — {_judul_tanggal(tgl)}", f"Selesai {selesai}/{total} ({selesai / total * 100:.0f}%)", "",
         "Ketuk habit untuk mencentang / membatalkan:"]
    tombol = [[(f"{'✅' if h['nilai'].get(tgl.day, False) else '⬜'} {h['nama'][:30]}", f"hb:{h['baris']}:{ymd}")]
              for h in data["habits"]]
    return "\n".join(L), tombol


def _streak(nilai, hari_ini):
    d = hari_ini if nilai.get(hari_ini, False) else hari_ini - 1
    n = 0
    while d >= 1 and nilai.get(d, False):
        n += 1
        d -= 1
    return n


def rekap_habit(data, tgl):
    """Ringkasan bulan berjalan sampai tanggal 'tgl': persen per habit dan streak."""
    hari = tgl.day
    baris = []
    for h in data["habits"]:
        ok = sum(1 for d in range(1, hari + 1) if h["nilai"].get(d, False))
        baris.append((h["nama"], ok / hari * 100, _streak(h["nilai"], hari), ok))
    total_ok = sum(b[3] for b in baris)
    total_persen = total_ok / (hari * len(baris)) * 100 if baris else 0
    urut = sorted(baris, key=lambda b: (-b[1], b[0]))
    tabel = [f"{'Habit':<26}{'%':>5}{'Streak':>8}"] + [f"{b[0][:25]:<26}{b[1]:>4.0f}%{b[2]:>8}" for b in urut]
    L = [f"<b>REKAP HABIT</b> — {BULAN_PENDEK[tgl.month - 1]} {tgl.year} (hari 1–{hari})",
         f"Rata-rata penyelesaian {total_persen:.0f}%", "", "<pre>" + esc("\n".join(tabel)) + "</pre>"]
    if len(urut) >= 2:
        L.append(f"Terkuat: {esc(urut[0][0])} ({urut[0][1]:.0f}%) · Paling perlu perhatian: {esc(urut[-1][0])} ({urut[-1][1]:.0f}%)")
    return "\n".join(L)


def konteks_habit(svc, sheet_id, sekarang):
    """Teks konteks untuk Gemini: daftar habit dan status hari ini."""
    tgl = sekarang.date()
    try:
        data = baca_habit(svc, sheet_id, tgl.year, tgl.month)
    except Exception as e:
        return f"Gagal membaca HABIT BUILDER: {e}"
    return f"Tanggal hari ini {tgl.isoformat()}. Habit:\n" + "\n".join(
        f"- {h['nama']} [{'sudah' if h['nilai'].get(tgl.day, False) else 'belum'}]" for h in data["habits"])


def kata_habit(data):
    """Kumpulan kata (>=4 huruf) dari nama habit, untuk mendeteksi pesan yang membahas habit."""
    return {w for h in data["habits"] for w in norm(h["nama"]).split() if len(w) >= 4}


# ---------- membaca perintah teks ----------
_REKAP = re.compile(r"(rekap habit|statistik habit|progres habit|progress habit|habit bulan ini)", re.I)
_HARI = re.compile(r"(habit (hari ini|ku|saya)|cek habit|checklist habit|kebiasaan hari ini|habit apa)", re.I)


def rute_teks(teks):
    """'rekap' / 'hari' kalau pesan meminta fitur habit, selain itu None."""
    t = teks.strip().lower()
    if t.startswith("/rekaphabit") or _REKAP.search(t):
        return "rekap"
    if t.startswith("/habit") or _HARI.search(t):
        return "hari"
    return None
