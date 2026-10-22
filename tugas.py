"""Otomatisasi TASK MANAGER (tab "Taks Work and life").

Bot hanya mengisi sel input (Tasks, Due Date, Priority, Status, Category, Note) dan mencentang checkbox.
Kolom "#" dan "Day Left" serta dashboard di atas tetap dihitung oleh rumus di sheet.
Posisi kolom dicari otomatis dari baris header, dan pilihan dropdown dibaca dari validasi sel.
"""
import difflib
import html
import re
import zlib
from datetime import date, datetime

from sheetutil import (baca_blok, baca_validasi, daftar_tab, kolom_huruf, kosong, norm, pilih_opsi, q, sel,
                       tgl_iso, tulis)

WAJIB = ("tasks", "due date", "priority", "status", "category")
OPSIONAL = ("note", "day left")
BULAN_PENDEK = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]


def esc(x):
    return html.escape(str(x))


def _crc(teks):
    return format(zlib.crc32(str(teks).strip().encode("utf-8")) & 0xFFFF, "04x")


# ---------- membaca ----------
def _cari_header(blok):
    for i, row in enumerate(blok):
        peta = {}
        for j, v in enumerate(row):
            k = str(v).strip().lower()
            if k in WAJIB + OPSIONAL and k not in peta:
                peta[k] = j
        if all(k in peta for k in WAJIB):
            return i, peta
    return None, None


def baca_tugas(svc, sheet_id):
    """Baca tab yang berisi tabel tugas. Return dict: tab, kolom, hdr, cb_col, next_row, tugas, blok."""
    for tab in daftar_tab(svc, sheet_id):
        if "backup" in tab.lower():
            continue
        blok = baca_blok(svc, sheet_id, tab, "A:AB")
        hdr, kolom = _cari_header(blok)
        if kolom is None:
            continue
        # Header "Tasks" kadang digabung (merge) mulai dari kolom checkbox. Kalau sel di bawah header
        # berisi checkbox (TRUE/FALSE), teks tugas sebenarnya ada satu kolom di kanannya.
        contoh = [sel(r, kolom["tasks"]) for r in blok[hdr + 1: hdr + 40]]
        if any(isinstance(v, bool) or str(v).strip().upper() in ("TRUE", "FALSE") for v in contoh):
            kolom["tasks"] += 1
        cb_col = kolom["tasks"] - 1  # checkbox ada tepat di kiri kolom Tasks
        daftar, next_idx = [], None
        for i in range(hdr + 1, min(len(blok), hdr + 1 + 800)):
            row = blok[i]
            nama = str(sel(row, kolom["tasks"])).strip()
            if not nama:
                if next_idx is None:
                    next_idx = i
                continue
            status = str(sel(row, kolom["status"])).strip()
            cb = sel(row, cb_col)
            daftar.append({
                "baris": i + 1, "tugas": nama, "due": tgl_iso(sel(row, kolom["due date"])),
                "priority": str(sel(row, kolom["priority"])).strip(), "status": status,
                "kategori": str(sel(row, kolom["category"])).strip(),
                "catatan": str(sel(row, kolom["note"])).strip() if "note" in kolom else "",
                "selesai": (cb is True) or ("done" in norm(status)),
                "cb_terisi": cb is True,
            })
        if next_idx is None:
            next_idx = max(len(blok), hdr + 1)
        return {"tab": tab, "kolom": kolom, "hdr": hdr, "cb_col": cb_col, "next_row": next_idx + 1,
                "tugas": daftar, "blok": blok}
    raise RuntimeError("Tabel tugas (kolom Tasks, Due Date, Priority, Status, Category) tidak ditemukan di TASK MANAGER.")


def baca_opsi(svc, sheet_id, data):
    """Pilihan dropdown Priority/Status/Category dari validasi sel; cadangan: nilai yang sudah dipakai."""
    baris_a1 = data["hdr"] + 2  # baris data pertama (1-based)
    peta = {"priority": "priority", "status": "status", "category": "kategori"}
    hasil = {}
    for nama, kunci in peta.items():
        a1 = f"{kolom_huruf(data['kolom'][nama])}{baris_a1}"
        nilai = baca_validasi(svc, sheet_id, data["tab"], a1)
        if not nilai:
            nilai = sorted({t[kunci] for t in data["tugas"] if t[kunci]})
        hasil[nama] = nilai
    return hasil


# ---------- menulis ----------
def _lama(data, baris, kolom):
    blok = data["blok"]
    return sel(blok[baris - 1], kolom) if baris - 1 < len(blok) else ""


def tambah_tugas(svc, sheet_id, items):
    """Tambah tugas baru di baris kosong berikutnya. Return (hasil, restore)."""
    data = baca_tugas(svc, sheet_id)
    opsi = baca_opsi(svc, sheet_id, data)
    kolom, tab = data["kolom"], data["tab"]
    baris = data["next_row"]
    updates, restore, hasil = [], [], []
    for it in items:
        nama = str(it.get("tugas") or it.get("task") or "").strip()
        if not nama:
            raise ValueError("Nama tugas kosong.")
        due = str(it.get("due") or "").strip()
        if due:
            try:
                datetime.strptime(due, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Format tanggal tidak valid: {due}")
        prio = pilih_opsi(opsi["priority"], it.get("priority"), "medium") or (opsi["priority"] or [""])[0]
        status = pilih_opsi(opsi["status"], it.get("status"), "planned") or (opsi["status"] or [""])[0]
        kat = pilih_opsi(opsi["category"], it.get("category"))
        if not kat:
            raise ValueError(f"Kategori '{it.get('category')}' tidak ada. Pilihan: {', '.join(opsi['category']) or '-'}")
        catatan = str(it.get("catatan") or "").strip()
        if catatan[:1] in ("=", "+", "-", "@"):
            catatan = "'" + catatan
        isi = [("tasks", nama), ("due date", due), ("priority", prio), ("status", status), ("category", kat)]
        if catatan and "note" in kolom:
            isi.append(("note", catatan))
        for label, nilai in isi:
            if label == "due date" and not nilai:
                continue
            rng = f"{q(tab)}!{kolom_huruf(kolom[label])}{baris}"
            updates.append({"range": rng, "values": [[nilai]]})
            restore.append({"range": rng, "values": [[_lama(data, baris, kolom[label])]]})
        duplikat = any(norm(t["tugas"]) == norm(nama) and not t["selesai"] for t in data["tugas"])
        hasil.append({"baris": baris, "tugas": nama, "due": due, "priority": prio, "status": status,
                      "kategori": kat, "catatan": it.get("catatan") or "", "duplikat": duplikat})
        baris += 1
    tulis(svc, sheet_id, updates)
    return hasil, restore


def selesaikan_tugas(svc, sheet_id, baris, crc):
    """Centang checkbox + set Status ke 'Done'. Return (nama_tugas, restore)."""
    data = baca_tugas(svc, sheet_id)
    t = next((x for x in data["tugas"] if x["baris"] == baris), None)
    if not t or _crc(t["tugas"]) != crc:
        raise ValueError("Daftar tugas sudah berubah. Kirim /tugas lagi untuk memuat ulang.")
    if t["selesai"]:
        raise ValueError("Tugas ini sudah selesai.")
    opsi = baca_opsi(svc, sheet_id, data)
    done = pilih_opsi(opsi["status"], "done")
    updates, restore = [], []
    if data["cb_col"] >= 0:
        rng = f"{q(data['tab'])}!{kolom_huruf(data['cb_col'])}{baris}"
        updates.append({"range": rng, "values": [[True]]})
        restore.append({"range": rng, "values": [[_lama(data, baris, data["cb_col"])]]})
    if done:
        rng = f"{q(data['tab'])}!{kolom_huruf(data['kolom']['status'])}{baris}"
        updates.append({"range": rng, "values": [[done]]})
        restore.append({"range": rng, "values": [[_lama(data, baris, data["kolom"]["status"])]]})
    tulis(svc, sheet_id, updates)
    return t["tugas"], restore


def cari_tugas_terbuka(data, kata):
    """Cari satu tugas terbuka dari kata kunci (substring atau kemiripan). Error kalau tidak jelas."""
    kunci = norm(kata)
    terbuka = [t for t in data["tugas"] if not t["selesai"]]
    if not kunci or not terbuka:
        raise ValueError("Tidak ada tugas terbuka yang cocok.")
    cocok = [t for t in terbuka if kunci in norm(t["tugas"]) or norm(t["tugas"]) in kunci]
    if not cocok:  # semua kata kunci muncul di judul tugas, walau tidak berurutan
        kata_kunci = kunci.split()
        cocok = [t for t in terbuka if all(any(k in w for w in norm(t["tugas"]).split()) for k in kata_kunci)]
    if len(cocok) == 1:
        return cocok[0]
    if len(cocok) > 1:
        raise ValueError(f"'{kata}' cocok dengan beberapa tugas: " + "; ".join(t["tugas"] for t in cocok[:5])
                         + ". Kirim /tugas lalu tekan tombol ✅ pada tugas yang dimaksud.")
    skor = sorted(((difflib.SequenceMatcher(None, kunci, norm(t["tugas"])).ratio(), t) for t in terbuka),
                  key=lambda x: -x[0])
    if skor[0][0] >= 0.6 and (len(skor) == 1 or skor[0][0] - skor[1][0] >= 0.1):
        return skor[0][1]
    raise ValueError(f"Tugas '{kata}' tidak ditemukan atau terlalu mirip beberapa tugas. "
                     "Kirim /tugas lalu tekan tombol ✅.")


def selesaikan_dengan_kata(svc, sheet_id, kata):
    data = baca_tugas(svc, sheet_id)
    t = cari_tugas_terbuka(data, kata)
    return selesaikan_tugas(svc, sheet_id, t["baris"], _crc(t["tugas"]))


# ---------- tampilan ----------
def _sisa_hari(t, hari):
    if not t["due"]:
        return None
    try:
        return (date.fromisoformat(t["due"]) - hari).days
    except ValueError:
        return None


def _tgl_pendek(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {BULAN_PENDEK[d.month - 1]}"


def kartu_tugas(data, sekarang, filter="semua", maks=10):
    """Return (html, baris_tombol). baris_tombol = [[(label, callback_data), ...], ...]."""
    hari = sekarang.date()
    terbuka = [t for t in data["tugas"] if not t["selesai"]]
    for t in terbuka:
        t["_sisa"] = _sisa_hari(t, hari)
    telat = [t for t in terbuka if t["_sisa"] is not None and t["_sisa"] < 0]
    hari_ini = [t for t in terbuka if t["_sisa"] == 0]
    if filter == "overdue":
        tampil, judul = telat, "Tugas overdue"
    elif filter == "hari":
        tampil, judul = telat + hari_ini, "Tugas hari ini"
    else:
        tampil, judul = terbuka, "Tugas terbuka"
    tampil = sorted(tampil, key=lambda t: (t["_sisa"] is None, t["_sisa"] if t["_sisa"] is not None else 0, t["baris"]))
    L = [f"<b>{judul.upper()}</b> — {hari.day} {BULAN_PENDEK[hari.month - 1]} {hari.year}",
         f"Terbuka {len(terbuka)} · Overdue {len(telat)} · Hari ini {len(hari_ini)}", ""]
    if not tampil:
        L.append("🎉 Tidak ada tugas pada daftar ini." if terbuka or filter == "semua" else "Tidak ada tugas.")
        return "\n".join(L), []
    tombol = []
    for n, t in enumerate(tampil[:maks], 1):
        if t["_sisa"] is None:
            ket = "tanpa tanggal"
        elif t["_sisa"] < 0:
            ket = f"{_tgl_pendek(t['due'])} · telat {-t['_sisa']} hari"
        elif t["_sisa"] == 0:
            ket = "hari ini"
        else:
            ket = f"{_tgl_pendek(t['due'])} · {t['_sisa']} hari lagi"
        ikon = "⚠️ " if (t["_sisa"] is not None and t["_sisa"] < 0) else ("📌 " if t["_sisa"] == 0 else "")
        info = " · ".join(x for x in (t["priority"], t["kategori"]) if x)
        L.append(f"{n}. {ikon}{esc(t['tugas'])}\n    {esc(ket)}" + (f" · {esc(info)}" if info else ""))
        tombol.append((f"✅ {n}", f"td:{t['baris']}:{_crc(t['tugas'])}"))
    if len(tampil) > maks:
        L.append(f"\n… dan {len(tampil) - maks} tugas lainnya.")
    L.append("\nTekan tombol ✅ untuk menandai selesai.")
    baris_tombol = [tombol[i:i + 5] for i in range(0, len(tombol), 5)]
    return "\n".join(L), baris_tombol


def konteks_tugas(svc, sheet_id, sekarang):
    """Teks konteks untuk Gemini: opsi dropdown + tugas terbuka."""
    try:
        data = baca_tugas(svc, sheet_id)
        opsi = baca_opsi(svc, sheet_id, data)
    except Exception as e:
        return f"Gagal membaca TASK MANAGER: {e}"
    L = [f"Opsi Priority: {' | '.join(opsi['priority'])}",
         f"Opsi Status: {' | '.join(opsi['status'])}",
         f"Opsi Category: {' | '.join(opsi['category'])}", "Tugas terbuka:"]
    terbuka = [t for t in data["tugas"] if not t["selesai"]]
    L += [f"- {t['tugas']} (due {t['due'] or '-'}, {t['priority']}, {t['kategori']})" for t in terbuka[:30]] or ["- (tidak ada)"]
    return "\n".join(L)


# ---------- membaca perintah teks ----------
_RUTE = [
    ("overdue", re.compile(r"(tugas.*overdue|overdue.*tugas|yang overdue|apa.*overdue)", re.I)),
    ("hari", re.compile(r"(tugas hari ini|to-?do hari ini|deadline hari ini)", re.I)),
    ("semua", re.compile(r"(daftar tugas|list tugas|cek tugas|lihat tugas|tugas (saya|ku)\b|\btugasku|apa (saja )?tugas|semua tugas)", re.I)),
]


def rute_teks(teks):
    """Kembalikan filter ('semua'/'hari'/'overdue') kalau pesan meminta daftar tugas, selain itu None."""
    t = teks.strip()
    if t.lower().startswith("/tugas"):
        return "semua"
    for filter_, pola in _RUTE:
        if pola.search(t):
            return filter_
    return None
