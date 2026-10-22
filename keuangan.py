"""Logika pencatat keuangan untuk template Budget_TRACKING.

Bot menulis langsung ke tabel "Transaction List" di tab bulan (mis. "September"),
memakai kategori yang ada di kolom BF:BJ tab itu. Posisi kolom dicari otomatis
dari baris header (Date / Type / Category / Amount / Notes), jadi tidak ada
alamat sel yang ditulis mati di kode.
"""
import calendar
import json
import re
from datetime import date, datetime, timedelta

BULAN_EN = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]
BULAN_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
            "Agustus", "September", "Oktober", "November", "Desember"]
GRUP = ["Debt", "Needs", "Wants", "Income", "Savings"]   # = isi kolom "Type"
LABEL = ("date", "type", "category", "amount", "notes")


# ---------- utilitas kecil ----------
def rupiah(n):
    return "Rp " + f"{int(round(n)):,}".replace(",", ".")


def _sel(row, i):
    return row[i] if i < len(row) else ""


def _kosong(v):
    return v is None or str(v).strip() == ""


def _q(tab):
    return "'" + tab.replace("'", "''") + "'"


def kolom_huruf(idx):
    """0 -> A, 25 -> Z, 26 -> AA"""
    idx += 1
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def _grup_kanonik(nama):
    for g in GRUP:
        if g.lower() == str(nama).strip().lower():
            return g
    return None


def _angka(v):
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v).replace(",", "")) or 0)
    except ValueError:
        return 0.0


def tgl_dari_sheet(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (date(1899, 12, 30) + timedelta(days=int(v))).strftime("%Y-%m-%d")
    return str(v).strip()


def parse_transaksi(teks):
    """Ambil array JSON dari output Gemini (toleran terhadap code fence / teks tambahan)."""
    bersih = re.sub(r"```(?:json)?", "", teks).strip()
    posisi = [p for p in (bersih.find("["), bersih.find("{")) if p != -1]
    if not posisi:
        raise ValueError("Tidak ada data transaksi (JSON) dari AI.")
    data, _ = json.JSONDecoder().raw_decode(bersih[min(posisi):])
    return data if isinstance(data, list) else [data]


# ---------- membaca sheet ----------
def daftar_tab(svc, sheet_id):
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def cari_tab_bulan(judul_tab, bulan):
    """Cari tab untuk bulan 1-12; terima nama Inggris atau Indonesia."""
    for nama in (BULAN_EN[bulan - 1], BULAN_ID[bulan - 1]):
        for t in judul_tab:
            if t.strip().lower() == nama.lower():
                return t
    return None


def baca_tab(svc, sheet_id, tab):
    """Baca satu tab bulan: posisi kolom, baris kosong berikutnya, transaksi, kategori."""
    res = svc.spreadsheets().values().batchGet(
        spreadsheetId=sheet_id,
        ranges=[f"{_q(tab)}!A:T", f"{_q(tab)}!BF:BJ"],
        valueRenderOption="UNFORMATTED_VALUE").execute()
    blok = res["valueRanges"][0].get("values", [])
    kat = res["valueRanges"][1].get("values", [])

    # 1) cari baris header Transaction List
    hdr, kolom = None, None
    for i, row in enumerate(blok):
        peta = {}
        for j, v in enumerate(row):
            k = str(v).strip().lower()
            if k in LABEL and k not in peta:
                peta[k] = j
        if len(peta) == len(LABEL):
            hdr, kolom = i, peta
            break
    if kolom is None:
        raise RuntimeError(f"Header Transaction List (Date/Type/Category/Amount/Notes) tidak ditemukan di tab {tab}.")

    # 2) baca baris transaksi yang sudah terisi (berurutan dari bawah header)
    transaksi = []
    i = hdr + 1
    while i < len(blok):
        row = blok[i]
        if all(_kosong(_sel(row, kolom[k])) for k in ("date", "category", "amount")):
            break
        transaksi.append({
            "baris": i + 1,
            "tanggal": tgl_dari_sheet(_sel(row, kolom["date"])),
            "tipe": _grup_kanonik(_sel(row, kolom["type"])) or str(_sel(row, kolom["type"])).strip(),
            "kategori": str(_sel(row, kolom["category"])).strip(),
            "jumlah": _angka(_sel(row, kolom["amount"])),
            "catatan": str(_sel(row, kolom["notes"])).strip(),
        })
        i += 1
    next_row = i + 1

    # 3) pengaman: kolom hasil deteksi harus terbukti berisi data di baris terakhir
    if transaksi:
        for k in ("date", "type", "category", "amount"):
            terisi = any(not _kosong(_sel(blok[hdr + n], kolom[k])) for n in range(max(1, len(transaksi) - 2), len(transaksi) + 1))
            if not terisi:
                raise RuntimeError(
                    f"Posisi kolom '{k}' di tab {tab} tidak cocok dengan isi tabel. Bot berhenti supaya tidak menulis di sel yang salah.")

    # 4) kategori per grup dari kolom BF:BJ
    kategori = {}
    hdr_k = None
    for i, row in enumerate(kat):
        if sum(1 for c in range(5) if _grup_kanonik(_sel(row, c))) >= 3:
            hdr_k = i
            break
    if hdr_k is not None:
        for c in range(5):
            g = _grup_kanonik(_sel(kat[hdr_k], c))
            if not g:
                continue
            kategori[g] = [str(r_[c]).strip() for r_ in kat[hdr_k + 1:] if c < len(r_) and not _kosong(r_[c])]

    return {"tab": tab, "blok": blok, "kolom": kolom, "next_row": next_row,
            "transaksi": transaksi, "kategori": kategori}


def sisa_dashboard(blok):
    """Angka di bawah judul 'Actual Amount Left to Spend' (hasil rumus dashboard), atau None."""
    for i, row in enumerate(blok):
        for j, v in enumerate(row):
            if isinstance(v, str) and "left to spend" in v.lower():
                for r2 in blok[i + 1:i + 12]:
                    for c in range(max(0, j - 6), j + 7):
                        x = _sel(r2, c)
                        if isinstance(x, (int, float)) and not isinstance(x, bool):
                            return x
                return None
    return None


def konteks_keuangan(svc, sheet_id, sekarang):
    """(ringkasan bulan ini, daftar kategori) sebagai teks untuk disematkan ke prompt Gemini."""
    if not sheet_id:
        return "Fitur keuangan belum dikonfigurasi (BUDGET_SHEET_ID kosong).", "-"
    try:
        tab = cari_tab_bulan(daftar_tab(svc, sheet_id), sekarang.month)
        if not tab:
            return f"Tab bulan {BULAN_EN[sekarang.month - 1]} belum ada di Budget_TRACKING.", "-"
        d = baca_tab(svc, sheet_id, tab)
    except Exception as e:
        return f"Gagal membaca sheet keuangan: {e}", "-"

    total = {g: 0.0 for g in GRUP}
    for t in d["transaksi"]:
        if t["tipe"] in total:
            total[t["tipe"]] += t["jumlah"]
    keluar = sum(v for g, v in total.items() if g != "Income")
    baris = [f"Tab {tab} (jumlah dari Transaction List):"]
    baris += [f"- {g}: {rupiah(v)}" for g, v in total.items()]
    baris.append(f"- Total uang keluar: {rupiah(keluar)}; selisih Income - uang keluar: {rupiah(total['Income'] - keluar)}")
    sisa = sisa_dashboard(d["blok"])
    if sisa is not None:
        baris.append(f"- Sisa budget menurut dashboard sheet (Actual Amount Left to Spend): {rupiah(sisa)}")
    if d["transaksi"]:
        baris.append("5 transaksi terakhir:")
        baris += [f"  {t['tanggal']} | {t['tipe']} | {t['kategori']} | {rupiah(t['jumlah'])} | {t['catatan']}"
                  for t in d["transaksi"][-5:]]
    daftar_kat = "\n".join(f"{g}: {', '.join(items)}" for g, items in d["kategori"].items()) or "-"
    return "\n".join(baris), daftar_kat


# ---------- menulis ke sheet ----------
def tulis_transaksi(svc, sheet_id, items, sekarang):
    """Tulis transaksi ke Transaction List tab bulan yang sesuai tanggalnya.

    Return (hasil, undo): hasil untuk balasan, undo untuk membatalkan lewat /undo.
    Semua validasi dijalankan dulu; tidak ada sel yang ditulis kalau ada yang tidak valid.
    """
    judul = daftar_tab(svc, sheet_id)
    per_tab = {}
    for t in items:
        tgl = str(t.get("tanggal") or sekarang.strftime("%Y-%m-%d")).strip()
        try:
            d = datetime.strptime(tgl, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Format tanggal tidak valid: {tgl}")
        jumlah = int(round(float(t.get("jumlah", 0))))
        if jumlah <= 0:
            raise ValueError("Jumlah harus lebih dari 0")
        tab = cari_tab_bulan(judul, d.month)
        if not tab:
            raise RuntimeError(
                f"Tab bulan {BULAN_EN[d.month - 1]} belum ada di Budget_TRACKING. "
                f"Duplikat tab bulan sebelumnya (klik kanan tab -> Duplikat), ganti namanya jadi "
                f"'{BULAN_EN[d.month - 1]}', lalu kirim ulang.")
        per_tab.setdefault(tab, []).append(
            (tgl, str(t.get("grup", "")).strip(), str(t.get("kategori", "")).strip(), jumlah, str(t.get("catatan", "")).strip()))

    rencana = []   # (tab, data_tab, [(baris, tgl, grup, kat, jumlah, catatan, duplikat)])
    for tab, daftar in per_tab.items():
        data = baca_tab(svc, sheet_id, tab)
        baris_no = data["next_row"]
        entri = []
        for tgl, grup, kat, jumlah, catatan in daftar:
            g = _grup_kanonik(grup)
            if not g:
                raise ValueError(f"Grup tidak dikenal: '{grup}'. Pilihan: {', '.join(GRUP)}")
            pilihan = data["kategori"].get(g, [])
            k = next((x for x in pilihan if x.lower() == kat.lower()), None)
            if not k:
                raise ValueError(f"Kategori '{kat}' tidak ada di grup {g} (tab {tab}). Pilihan: {', '.join(pilihan) or '-'}")
            duplikat = any(t["tanggal"] == tgl and int(round(t["jumlah"])) == jumlah for t in data["transaksi"])
            entri.append((baris_no, tgl, g, k, jumlah, catatan, duplikat))
            baris_no += 1
        rencana.append((tab, data, entri))

    hasil, undo = [], []
    for tab, data, entri in rencana:
        kolom = data["kolom"]
        updates = []
        for baris_no, tgl, g, k, jumlah, catatan, _ in entri:
            teks_catatan = ("'" + catatan) if catatan[:1] in ("=", "+", "-", "@") else catatan
            for label, nilai in (("date", tgl), ("type", g), ("category", k), ("amount", jumlah), ("notes", teks_catatan)):
                updates.append({"range": f"{_q(tab)}!{kolom_huruf(kolom[label])}{baris_no}", "values": [[nilai]]})
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id, body={"valueInputOption": "USER_ENTERED", "data": updates}).execute()
        undo.append({"tab": tab, "kolom": kolom, "baris": [e[0] for e in entri]})
        for baris_no, tgl, g, k, jumlah, catatan, duplikat in entri:
            hasil.append({"tab": tab, "baris": baris_no, "tanggal": tgl, "grup": g, "kategori": k,
                          "jumlah": jumlah, "catatan": catatan, "duplikat": duplikat})
    return hasil, undo


def hapus_transaksi(svc, sheet_id, undo):
    """Kosongkan sel isian (Date/Type/Category/Amount/Notes) dari transaksi terakhir. Baris tidak dihapus."""
    ranges = []
    for u in undo:
        for r in u["baris"]:
            for label in LABEL:
                ranges.append(f"{_q(u['tab'])}!{kolom_huruf(u['kolom'][label])}{r}")
    svc.spreadsheets().values().batchClear(spreadsheetId=sheet_id, body={"ranges": ranges}).execute()
    return sum(len(u["baris"]) for u in undo)


# ======================================================================
# ANALISIS KEUANGAN PERSONAL (dihitung di Python; Gemini hanya menafsirkan)
# ======================================================================
def ringkas_bulan(transaksi):
    total = {g: 0.0 for g in GRUP}
    per_kat = {}
    for t in transaksi:
        g = t["tipe"]
        if g not in total:
            continue
        total[g] += t["jumlah"]
        if g != "Income":
            kunci = (g, t["kategori"])
            per_kat[kunci] = per_kat.get(kunci, 0.0) + t["jumlah"]
    keluar = sum(v for g, v in total.items() if g != "Income")
    return {"total": total, "per_kat": per_kat, "income": total["Income"], "keluar": keluar}


def baca_riwayat(svc, sheet_id, sekarang, jumlah_bulan=6):
    """Baca tab bulan yang ada, mundur dari bulan berjalan. Return (riwayat lama->baru, catatan_gagal)."""
    judul = daftar_tab(svc, sheet_id)
    riwayat, gagal = [], []
    y, m = sekarang.year, sekarang.month
    for _ in range(jumlah_bulan):
        tab = cari_tab_bulan(judul, m)
        if tab:
            try:
                d = baca_tab(svc, sheet_id, tab)
                riwayat.append({"tab": tab, "tahun": y, "bulan": m, "transaksi": d["transaksi"]})
            except Exception as e:
                gagal.append(f"{tab}: {e}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    riwayat.reverse()
    return riwayat, gagal


def hitung_metrik(riwayat, sekarang):
    """Hitung metrik kondisi keuangan dari riwayat tab bulan. None kalau tidak ada data."""
    if not riwayat:
        return None
    terbaru = riwayat[-1]
    sebelumnya = [r for r in riwayat[:-1] if r["transaksi"]]
    now = ringkas_bulan(terbaru["transaksi"])
    prev = [ringkas_bulan(r["transaksi"]) for r in sebelumnya]
    berjalan = (terbaru["tahun"], terbaru["bulan"]) == (sekarang.year, sekarang.month)

    # acuan pemasukan untuk rasio
    acuan, acuan_label = now["income"], "pemasukan tercatat bulan ini"
    if acuan <= 0 and prev and prev[-1]["income"] > 0:
        acuan = prev[-1]["income"]
        acuan_label = f"pemasukan {sebelumnya[-1]['tab']} (bulan ini belum ada pemasukan tercatat)"
    elif acuan <= 0:
        acuan_label = "tidak ada data pemasukan"

    def persen(v):
        return (v / acuan * 100) if acuan > 0 else None

    rasio = {g: persen(now["total"][g]) for g in ("Needs", "Wants", "Savings", "Debt")}
    rasio["Needs+Debt"] = persen(now["total"]["Needs"] + now["total"]["Debt"])

    def rata(fn):
        return (sum(fn(p) for p in prev) / len(prev)) if prev else None

    rata_grup = {g: rata(lambda p, g=g: p["total"][g]) for g in GRUP}

    kategori_teratas, kategori_naik, kategori_baru = [], [], []
    for (g, k), v in sorted(now["per_kat"].items(), key=lambda kv: kv[1], reverse=True):
        avg = rata(lambda p, g=g, k=k: p["per_kat"].get((g, k), 0.0))
        item = {"grup": g, "kategori": k, "jumlah": v, "rata_sebelumnya": avg}
        if len(kategori_teratas) < 6:
            kategori_teratas.append(item)
        if avg is not None and avg > 0 and v > avg * 1.3 and (v - avg) >= 100000:
            kategori_naik.append(item)
        elif avg is not None and avg == 0 and v >= 100000:
            kategori_baru.append(item)

    terbesar = sorted((t for t in terbaru["transaksi"] if t["tipe"] != "Income"),
                      key=lambda t: t["jumlah"], reverse=True)[:3]

    proyeksi = None
    if berjalan and sekarang.day >= 7:
        hb = calendar.monthrange(sekarang.year, sekarang.month)[1]
        f = hb / sekarang.day
        proyeksi = {"Wants": now["total"]["Wants"] * f,
                    "Needs+Wants": (now["total"]["Needs"] + now["total"]["Wants"]) * f,
                    "hari": sekarang.day, "hari_bulan": hb}

    return {"tab": terbaru["tab"], "berjalan": berjalan, "now": now, "acuan": acuan, "acuan_label": acuan_label,
            "rasio": rasio, "rata_grup": rata_grup, "jumlah_bulan_pembanding": len(prev),
            "kategori_teratas": kategori_teratas, "kategori_naik": kategori_naik, "kategori_baru": kategori_baru,
            "terbesar": terbesar, "proyeksi": proyeksi, "n_transaksi": len(terbaru["transaksi"]),
            "tab_pembanding": [r["tab"] for r in sebelumnya]}


def _pct(v):
    return "n/a" if v is None else f"{v:.0f}%"


def format_analisis(m, sekarang, gagal=()):
    """Ubah metrik jadi teks ringkas untuk disematkan ke prompt Gemini."""
    if not m:
        return "Belum ada tab bulan yang bisa dianalisis."
    n = m["now"]
    L = []
    if m["berjalan"]:
        L.append(f"Periode: tab {m['tab']} (bulan berjalan, hari ke-{sekarang.day}); {m['n_transaksi']} transaksi tercatat.")
    else:
        L.append(f"Periode: tab {m['tab']} (BUKAN bulan berjalan; tab bulan ini belum ada); {m['n_transaksi']} transaksi.")
    L.append(f"Pemasukan: {rupiah(n['income'])}. Uang keluar total: {rupiah(n['keluar'])}. "
             f"Arus kas (pemasukan - uang keluar): {rupiah(n['income'] - n['keluar'])}.")
    L.append("Per grup: " + "; ".join(f"{g} {rupiah(n['total'][g])}" for g in GRUP if g != "Income") + ".")
    r = m["rasio"]
    L.append(f"Rasio terhadap {m['acuan_label']} ({rupiah(m['acuan'])}): Needs {_pct(r['Needs'])}, Wants {_pct(r['Wants'])}, "
             f"Savings {_pct(r['Savings'])}, Debt (cicilan/tagihan kartu) {_pct(r['Debt'])}, Needs+Debt {_pct(r['Needs+Debt'])}. "
             f"Pembanding 50/30/20: kebutuhan (Needs+Debt) 50%, Wants 30%, Savings 20%.")
    if m["jumlah_bulan_pembanding"]:
        rg = m["rata_grup"]
        L.append(f"Rata-rata {m['jumlah_bulan_pembanding']} bulan sebelumnya ({', '.join(m['tab_pembanding'])}): "
                 + "; ".join(f"{g} {rupiah(rg[g])}" for g in GRUP) + ".")
    else:
        L.append("Belum ada bulan pembanding dengan data (hanya bulan ini).")
    if m["kategori_teratas"]:
        bagian = []
        for i in m["kategori_teratas"]:
            s = f"{i['grup']} › {i['kategori']} {rupiah(i['jumlah'])}"
            if i["rata_sebelumnya"] is not None:
                s += f" (rata-rata sebelumnya {rupiah(i['rata_sebelumnya'])})"
            bagian.append(s)
        L.append("Kategori terbesar: " + "; ".join(bagian) + ".")
    if m["kategori_naik"]:
        L.append("Kategori naik tajam vs rata-rata sebelumnya: "
                 + "; ".join(f"{i['kategori']} +{rupiah(i['jumlah'] - i['rata_sebelumnya'])}" for i in m["kategori_naik"]) + ".")
    if m["kategori_baru"]:
        L.append("Kategori yang tidak muncul di bulan-bulan sebelumnya: "
                 + "; ".join(f"{i['kategori']} {rupiah(i['jumlah'])}" for i in m["kategori_baru"]) + ".")
    if m["terbesar"]:
        L.append("Transaksi keluar terbesar: " + "; ".join(
            f"{t['tanggal']} {t['kategori']} {rupiah(t['jumlah'])}" + (f" ({t['catatan']})" if t["catatan"] else "") for t in m["terbesar"]) + ".")
    if m["proyeksi"]:
        p = m["proyeksi"]
        L.append(f"Proyeksi kasar akhir bulan (laju hari 1-{p['hari']} dari {p['hari_bulan']} hari): "
                 f"Wants {rupiah(p['Wants'])}, Needs+Wants {rupiah(p['Needs+Wants'])}. Cicilan/tabungan dianggap sudah dibayar.")
    L.append("Keterbatasan: saldo tabungan/dana darurat TIDAK tercatat di data ini (hanya setoran ke grup Savings).")
    for g in gagal:
        L.append(f"Peringatan: gagal membaca tab {g}")
    return "\n".join(L)


def analisis_keuangan(svc, sheet_id, sekarang):
    """Teks analisis siap sematkan ke prompt."""
    if not sheet_id:
        return "Fitur keuangan belum dikonfigurasi (BUDGET_SHEET_ID kosong)."
    try:
        riwayat, gagal = baca_riwayat(svc, sheet_id, sekarang)
        return format_analisis(hitung_metrik(riwayat, sekarang), sekarang, gagal)
    except Exception as e:
        return f"Gagal menghitung analisis keuangan: {e}"