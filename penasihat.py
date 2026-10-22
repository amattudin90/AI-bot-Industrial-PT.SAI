"""Kartu status & analisis keuangan personal.

Semua angka dihitung di sini (deterministik). Hasilnya berupa teks HTML untuk Telegram.
Gemini hanya dipakai di bot.py untuk saran singkat di atas angka-angka ini.
"""
import html
import re

from keuangan import BULAN_ID, GRUP, ringkas_bulan

MENU = [
    ("analisis", "Analisis pengeluaran"),
    ("budget", "Buat budget bulan depan"),
    ("simulasi", "Simulasi penghematan"),
    ("debt", "Analisis debt"),
    ("savings", "Buat target savings"),
]


# ---------- format ----------
def rp(v):
    """33300000 -> 'Rp33.30 jt'; -23260000 -> '-Rp23.26 jt'; 450000 -> 'Rp450 rb'."""
    neg = v < 0
    a = abs(v)
    if a >= 1e6:
        s = f"Rp{a / 1e6:.2f} jt"
    elif a >= 1e3:
        s = f"Rp{a / 1e3:.0f} rb"
    else:
        s = f"Rp{a:.0f}"
    return ("-" if neg else "") + s


def esc(x):
    return html.escape(str(x))


def strip_html(teks):
    return html.unescape(re.sub(r"</?[a-z]+>", "", teks))


def _tabel(baris):
    return "<pre>" + esc("\n".join(baris)) + "</pre>"


def _menu_teks():
    return ["<b>Saya bisa bantu:</b>"] + [f"{i}. {label}" for i, (_, label) in enumerate(MENU, 1)]


# ---------- membaca perintah teks ----------
def parse_rupiah(teks):
    """'30jt' / '30 juta' / '2,5jt' / '500rb' / '30000000' -> float, atau None."""
    satuan = {"jt": 1e6, "juta": 1e6, "rb": 1e3, "ribu": 1e3, "k": 1e3, "m": 1e9, "miliar": 1e9}
    for mm in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(jt|juta|rb|ribu|miliar|k|m)\b", teks, re.I):
        return float(mm.group(1).replace(",", ".")) * satuan[mm.group(2).lower()]
    for mm in re.finditer(r"\d{1,3}(?:[.,]\d{3})+|\d{6,}", teks):
        return float(re.sub(r"[.,]", "", mm.group(0)))
    return None


def parse_bulan(teks):
    mm = re.search(r"(\d+)\s*(bulan|bln)\b", teks, re.I)
    if mm:
        return int(mm.group(1))
    mm = re.search(r"(\d+)\s*tahun\b", teks, re.I)
    return int(mm.group(1)) * 12 if mm else None


_RUTE = [
    ("simulasi", re.compile(r"simulasi", re.I)),
    ("savings", re.compile(r"(target (tabungan|savings?)|buat target|dana darurat)", re.I)),
    ("debt", re.compile(r"analisis (debt|utang|hutang)", re.I)),
    ("budget", re.compile(r"(budget bulan (depan|selanjutnya)|buat budget|rencana budget)", re.I)),
    ("analisis", re.compile(r"analisis pengeluaran", re.I)),
    ("status", re.compile(
        r"(\baman (nggak|ngga|gak|tidak|kah)\b|\bamankah\b|status keuangan|kondisi keuangan|cek keuangan|"
        r"keuangan(ku| saya)?\s+(sehat|aman|gimana|bagaimana))", re.I)),
]


def rute_teks(teks):
    """Kembalikan (aksi, parameter) kalau pesan meminta salah satu fitur penasihat, selain itu None."""
    t = teks.strip()
    if t.lower().startswith(("/status", "/kondisi")):
        return "status", {}
    for aksi, pola in _RUTE:
        if pola.search(t):
            if aksi == "simulasi":
                mm = re.search(r"(\d{1,3})\s*%", t)
                return aksi, {"persen": float(mm.group(1)) if mm else None}
            if aksi == "savings":
                return aksi, {"target": parse_rupiah(t), "bulan": parse_bulan(t)}
            return aksi, {}
    return None


# ---------- basis perhitungan ----------
def baseline(riwayat, sekarang, maks=3):
    """Bulan yang dipakai sebagai kebiasaan: bulan berjalan yang masih awal tidak dipakai kalau ada bulan lain."""
    bl = [{"tab": r["tab"], "tahun": r["tahun"], "bulan": r["bulan"], "r": ringkas_bulan(r["transaksi"])}
          for r in riwayat if r["transaksi"]]
    if not bl:
        return []
    terbaru = bl[-1]
    berjalan = (terbaru["tahun"], terbaru["bulan"]) == (sekarang.year, sekarang.month)
    if berjalan and sekarang.day < 25 and len(bl) > 1:
        bl = bl[:-1]
    return bl[-maks:]


def rata_baseline(bl):
    n = len(bl)
    inc = [b["r"]["income"] for b in bl if b["r"]["income"] > 0]
    kat = {}
    for b in bl:
        for key, v in b["r"]["per_kat"].items():
            kat[key] = kat.get(key, 0.0) + v / n
    grup = {g: sum(b["r"]["total"][g] for b in bl) / n for g in GRUP}
    terbaru = bl[-1]["r"]["total"]
    # Kewajiban (Debt, Needs) tidak dianggap turun sendiri: pakai yang lebih tinggi antara rata-rata dan bulan terbaru.
    wajib = {g: max(grup[g], terbaru[g]) for g in ("Debt", "Needs")}
    return {"n": n, "tabs": [b["tab"] for b in bl],
            "income": (sum(inc) / len(inc)) if inc else 0.0,
            "grup": grup, "wajib": wajib, "kat": kat}


# ---------- kartu ----------
def kartu_status(m, sekarang):
    n = m["now"]
    t = n["total"]
    income, spending, savings = n["income"], n["keluar"], t["Savings"]
    net = income - spending
    tabel = _tabel([f"{k:<14}{v}" for k, v in
                    (("Income", rp(income)), ("Spending", rp(spending)), ("Savings", rp(savings)), ("Net Cashflow", rp(net)))])
    L = ["<b>FINANCIAL STATUS</b>", f"<i>Periode: {esc(m['tab'])}</i>", "", tabel, ""]
    if not m["berjalan"]:
        L.append(f"ℹ️ Tab bulan ini belum ada, yang ditampilkan data tab {esc(m['tab'])}.")
    if income <= 0:
        L.append("ℹ️ Pemasukan bulan ini belum tercatat, jadi cashflow belum bisa dinilai.")
    elif net < 0:
        L.append("⚠️ Cashflow bulan ini negatif.")
    else:
        L.append(f"✅ Cashflow bulan ini positif (sisa {rp(net)}).")
    if income > 0 and t["Debt"] / income * 100 > 35:
        L.append(f"⚠️ Debt memakan {t['Debt'] / income * 100:.0f}% dari pemasukan (patokan umum ≤ 30–35%).")
    if spending > 0:
        judul = "Penyebab utama:" if (income > 0 and net < 0) else "Komposisi pengeluaran:"
        urut = sorted(((g, t[g]) for g in ("Debt", "Needs", "Wants", "Savings")), key=lambda x: -x[1])
        L += ["", f"<b>{judul}</b>"] + [f"{g} {v / spending * 100:.1f}%" for g, v in urut if v > 0]
    else:
        L += ["", "Belum ada pengeluaran tercatat bulan ini."]
    L += [""] + _menu_teks()
    return "\n".join(L)


def kartu_analisis(m):
    n = m["now"]
    keluar = n["keluar"]
    L = [f"<b>ANALISIS PENGELUARAN</b> — {esc(m['tab'])}",
         f"Total keluar {rp(keluar)} dari pemasukan {rp(n['income'])}", ""]
    if keluar <= 0:
        return "\n".join(L + ["Belum ada pengeluaran tercatat."])
    L.append("<b>Kategori terbesar</b>")
    for i, it in enumerate(m["kategori_teratas"], 1):
        s = f"{i}. {esc(it['grup'])} › {esc(it['kategori'])} — {rp(it['jumlah'])} ({it['jumlah'] / keluar * 100:.1f}%)"
        if it["rata_sebelumnya"] is not None and it["rata_sebelumnya"] > 0:
            s += f" | rata-rata sebelumnya {rp(it['rata_sebelumnya'])}"
        L.append(s)
    if m["kategori_naik"]:
        L += ["", "<b>Naik tajam dibanding rata-rata</b>"] + [
            f"• {esc(i['kategori'])}: +{rp(i['jumlah'] - i['rata_sebelumnya'])}" for i in m["kategori_naik"]]
    if m["kategori_baru"]:
        baru = m["kategori_baru"]
        L += ["", "<b>Tidak muncul di bulan-bulan sebelumnya</b>"] + [
            f"• {esc(i['kategori'])}: {rp(i['jumlah'])}" for i in baru[:5]]
        if len(baru) > 5:
            L.append(f"• dan {len(baru) - 5} kategori lain")
    if m["terbesar"]:
        L += ["", "<b>Transaksi keluar terbesar</b>"] + [
            f"• {esc(t['tanggal'])} {esc(t['kategori'])} {rp(t['jumlah'])}" + (f" ({esc(t['catatan'])})" if t["catatan"] else "")
            for t in m["terbesar"]]
    if m["proyeksi"]:
        p = m["proyeksi"]
        L += ["", f"<b>Proyeksi kasar akhir bulan</b> (laju hari 1–{p['hari']} dari {p['hari_bulan']} hari)",
              f"Wants {rp(p['Wants'])}; Needs+Wants {rp(p['Needs+Wants'])}"]
    return "\n".join(L)


def kartu_simulasi(m, persen=None):
    n = m["now"]
    wants = n["total"]["Wants"]
    net = n["income"] - n["keluar"]
    L = [f"<b>SIMULASI PENGHEMATAN</b> — {esc(m['tab'])}",
         f"Net cashflow sekarang: {rp(net)}", f"Wants bulan ini: {rp(wants)}", ""]
    if n["income"] <= 0:
        L.append("ℹ️ Pemasukan bulan ini belum tercatat, jadi net cashflow di bawah belum mencerminkan kondisi sebenarnya.")
    if wants <= 0:
        return "\n".join(L + ["Belum ada pengeluaran Wants tercatat, jadi tidak ada yang bisa dipangkas dari grup ini."])
    daftar = [10, 20, 30, 50, 100]
    if persen and 0 < persen <= 100 and persen not in daftar:
        daftar = sorted(daftar + [persen])
    baris = [f"{'Potong Wants':<14}{'Hemat':<13}Net cashflow"]
    for p in daftar:
        h = wants * p / 100
        baris.append(f"{(f'{p:g}%'):<14}{rp(h):<13}{rp(net + h)}")
    L.append(_tabel(baris))
    top = sorted(((k, v) for (g, k), v in n["per_kat"].items() if g == "Wants"), key=lambda x: -x[1])[:3]
    if top:
        h = sum(v for _, v in top) * 0.25
        L.append(f"Potong 25% di 3 Wants terbesar ({esc(', '.join(k for k, _ in top))}): hemat {rp(h)} → net {rp(net + h)}")
    if net < 0:
        butuh = -net
        if butuh <= wants:
            L.append(f"Agar net cashflow = 0, Wants perlu dipotong {rp(butuh)} ({butuh / wants * 100:.0f}% dari Wants).")
        else:
            L.append(f"Agar net cashflow = 0 dibutuhkan penghematan {rp(butuh)}, lebih besar dari seluruh Wants ({rp(wants)}). "
                     "Memotong Wants saja tidak cukup; perlu juga menyentuh Debt/Needs atau menambah pemasukan.")
    L.append("Coba persen lain: ketik misalnya “simulasi hemat 25%”.")
    return "\n".join(L)


def kartu_debt(m):
    n = m["now"]
    debt = n["total"]["Debt"]
    income = n["income"]
    L = [f"<b>ANALISIS DEBT</b> — {esc(m['tab'])}"]
    if debt <= 0:
        return "\n".join(L + ["Belum ada pembayaran Debt tercatat bulan ini."])
    baris = f"Debt bulan ini: {rp(debt)}"
    if income > 0:
        baris += f" = {debt / income * 100:.0f}% dari pemasukan (patokan umum ≤ 30–35%)"
    L.append(baris)
    if m["jumlah_bulan_pembanding"] and m["rata_grup"]["Debt"] is not None:
        L.append(f"Rata-rata {m['jumlah_bulan_pembanding']} bulan sebelumnya: {rp(m['rata_grup']['Debt'])}")
    rincian = sorted(((k, v) for (g, k), v in n["per_kat"].items() if g == "Debt"), key=lambda x: -x[1])
    L += ["", "<b>Rincian</b>"] + [f"• {esc(k)} — {rp(v)} ({v / debt * 100:.0f}% dari Debt)" for k, v in rincian]
    L += ["", "ℹ️ Data hanya mencatat pembayaran, bukan sisa pokok atau bunga. "
              "Kirim bunga dan sisa tagihan tiap kartu/cicilan supaya bisa diurutkan mana yang paling mahal."]
    return "\n".join(L)


def kartu_budget(riwayat, sekarang):
    bl = baseline(riwayat, sekarang)
    if not bl:
        return "Belum ada data bulan sebelumnya untuk menyusun budget."
    a = rata_baseline(bl)
    g = a["grup"]
    income = a["income"]
    nama = BULAN_ID[sekarang.month % 12]
    L = [f"<b>BUDGET {nama.upper()} (USULAN)</b>",
         f"<i>Dasar: {a['n']} bulan ({esc(', '.join(a['tabs']))}). Debt dan Needs memakai nilai tertinggi antara rata-rata dan bulan terbaru, "
         f"karena kewajiban tidak turun sendiri</i>", ""]
    if income <= 0:
        return "\n".join(L + ["Belum ada pemasukan tercatat di bulan dasar, jadi budget belum bisa disusun."])
    w = a["wajib"]
    sisa = income - w["Debt"] - w["Needs"]
    target_sav = 0.2 * income
    if sisa <= 0:
        wants_u = sav_u = 0.0
    else:
        sav_u = min(target_sav, sisa)
        wants_u = min(g["Wants"], sisa - sav_u)
        sav_u += sisa - sav_u - wants_u  # kelebihan masuk ke tabungan
    baris = [f"{'Grup':<9}{'Rata-rata':<13}{'Usulan':<13}% pemasukan"]
    for nama_g, rata, usul in (("Debt", g["Debt"], w["Debt"]), ("Needs", g["Needs"], w["Needs"]),
                               ("Wants", g["Wants"], wants_u), ("Savings", g["Savings"], sav_u)):
        baris.append(f"{nama_g:<9}{rp(rata):<13}{rp(usul):<13}{usul / income * 100:.0f}%")
    L += [f"Pemasukan acuan: {rp(income)}", _tabel(baris)]
    if sisa <= 0:
        L.append(f"⚠️ Debt + Needs ({rp(w['Debt'] + w['Needs'])}) sudah melebihi pemasukan acuan; "
                 f"kekurangan {rp(-sisa)} bahkan sebelum Wants dan Savings. Budget tidak bisa seimbang tanpa menurunkan kewajiban atau menambah pemasukan.")
    else:
        if wants_u < g["Wants"] - 1:
            L.append(f"Wants perlu turun dari {rp(g['Wants'])} ke {rp(wants_u)} ({(1 - wants_u / g['Wants']) * 100:.0f}% lebih rendah) "
                     f"agar tabungan {rp(sav_u)} tercapai.")
        wk = {k: v for (gg, k), v in a["kat"].items() if gg == "Wants" and v > 0}
        total_wk = sum(wk.values())
        if wants_u > 0 and total_wk > 0:
            L += ["", "<b>Batas Wants per kategori</b>"] + [
                f"• {esc(k)}: {rp(wants_u * v / total_wk)}" for k, v in sorted(wk.items(), key=lambda x: -x[1])[:5]]
    return "\n".join(L)


def kartu_savings(m, riwayat, sekarang, target=None, bulan=None):
    bl = baseline(riwayat, sekarang)
    if not bl:
        return "Belum ada data untuk menghitung target savings."
    a = rata_baseline(bl)
    g = a["grup"]
    income = a["income"]
    kewajiban = a["wajib"]["Debt"] + a["wajib"]["Needs"]
    kapasitas = income - kewajiban - g["Wants"]
    kap_hemat = kapasitas + 0.2 * g["Wants"]
    L = ["<b>TARGET SAVINGS</b>", f"<i>Dasar: rata-rata {a['n']} bulan ({esc(', '.join(a['tabs']))})</i>", "",
         f"Pemasukan rata-rata: {rp(income)}",
         f"Kewajiban bulanan (Debt + Needs): {rp(kewajiban)}",
         f"Wants rata-rata: {rp(g['Wants'])}",
         f"Kapasitas menabung (pemasukan − kewajiban − Wants rata-rata): {rp(kapasitas)}",
         f"Setoran Savings rata-rata saat ini: {rp(g['Savings'])}", ""]
    if income <= 0:
        return "\n".join(L + ["Belum ada pemasukan tercatat di bulan dasar."])
    L.append(f"Dana darurat ideal (3–6× kewajiban bulanan): {rp(3 * kewajiban)} – {rp(6 * kewajiban)}")
    if target:
        if bulan:
            per_bulan = target / bulan
            L.append(f"Target {rp(target)} dalam {bulan} bulan → butuh {rp(per_bulan)} per bulan.")
            if per_bulan <= kapasitas:
                L.append(f"✅ Masih muat dalam kapasitas menabung saat ini ({rp(kapasitas)}).")
            else:
                L.append(f"⚠️ Kurang {rp(per_bulan - kapasitas)} per bulan dari kapasitas saat ini; "
                         f"dengan Wants dipangkas 20% kapasitasnya {rp(kap_hemat)}.")
        elif kapasitas > 0:
            L.append(f"Target {rp(target)}: sekitar {target / kapasitas:.0f} bulan pada kapasitas saat ini "
                     f"({target / kap_hemat:.0f} bulan jika Wants dipangkas 20%).")
        else:
            L.append(f"Target {rp(target)}: kapasitas menabung saat ini nol atau negatif, jadi belum ada jalur waktu yang realistis.")
    elif kapasitas > 0:
        L.append(f"Pada kapasitas saat ini: 3× kewajiban tercapai sekitar {3 * kewajiban / kapasitas:.0f} bulan, "
                 f"6× sekitar {6 * kewajiban / kapasitas:.0f} bulan.")
    else:
        L.append("⚠️ Kapasitas menabung saat ini nol atau negatif; target tabungan baru realistis setelah pengeluaran turun atau pemasukan naik.")
    L += ["", "ℹ️ Saldo tabungan tidak ada di sheet (hanya setoran), jadi jumlah yang sudah terkumpul tidak dihitung.",
          "Contoh menentukan target sendiri: “target tabungan 30jt 12 bulan”."]
    return "\n".join(L)


def kartu(aksi, m, riwayat, sekarang, params=None):
    params = params or {}
    if aksi == "status":
        return kartu_status(m, sekarang)
    if aksi == "analisis":
        return kartu_analisis(m)
    
    if aksi == "budget":
        return kartu_budget(riwayat, sekarang)
    if aksi == "simulasi":
        return kartu_simulasi(m, params.get("persen"))
    if aksi == "debt":
        return kartu_debt(m)
    if aksi == "savings":
        return kartu_savings(m, riwayat, sekarang, params.get("target"), params.get("bulan"))
    raise ValueError(f"Aksi tidak dikenal: {aksi}")