"""Utilitas kecil untuk membaca/menulis Google Sheets (dipakai tugas.py dan habit.py)."""
import json
import re
from datetime import date, timedelta


def q(tab):
    """Nama tab yang aman untuk notasi A1."""
    return "'" + tab.replace("'", "''") + "'"


def sel(row, i):
    return row[i] if 0 <= i < len(row) else ""


def kosong(v):
    return v is None or str(v).strip() == ""


def kolom_huruf(idx):
    """0 -> A, 25 -> Z, 26 -> AA"""
    idx += 1
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def norm(teks):
    """Huruf kecil tanpa emoji/simbol, untuk membandingkan nama."""
    return re.sub(r"[^a-z0-9 ]", "", str(teks).lower()).strip()


def tgl_iso(v):
    """Isi sel tanggal (serial number atau teks) -> 'YYYY-MM-DD', atau '' kalau kosong/tidak dikenali."""
    if isinstance(v, bool) or v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        try:
            return (date(1899, 12, 30) + timedelta(days=int(v))).strftime("%Y-%m-%d")
        except OverflowError:
            return ""
    s = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def parse_json_array(teks):
    """Ambil array JSON dari output Gemini (toleran terhadap code fence / teks tambahan)."""
    bersih = re.sub(r"```(?:json)?", "", teks).strip()
    posisi = [p for p in (bersih.find("["), bersih.find("{")) if p != -1]
    if not posisi:
        raise ValueError("Tidak ada data (JSON) dari AI.")
    data, _ = json.JSONDecoder().raw_decode(bersih[min(posisi):])
    return data if isinstance(data, list) else [data]


def daftar_tab(svc, sheet_id):
    meta = svc.spreadsheets().get(spreadsheetId=sheet_id, fields="sheets.properties.title").execute()
    return [s["properties"]["title"] for s in meta.get("sheets", [])]


def baca_blok(svc, sheet_id, tab, rentang):
    res = svc.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=f"{q(tab)}!{rentang}", valueRenderOption="UNFORMATTED_VALUE").execute()
    return res.get("values", [])


def tulis(svc, sheet_id, updates):
    """updates: [{'range': ..., 'values': [[...]]}]. Dipakai juga untuk memulihkan nilai lama (/undo)."""
    if updates:
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=sheet_id, body={"valueInputOption": "USER_ENTERED", "data": updates}).execute()


def baca_validasi(svc, sheet_id, tab, a1):
    """Daftar pilihan dropdown pada satu sel, atau None kalau tidak ada / tidak terbaca."""
    try:
        res = svc.spreadsheets().get(
            spreadsheetId=sheet_id, ranges=[f"{q(tab)}!{a1}"],
            fields="sheets.data.rowData.values.dataValidation").execute()
        dv = res["sheets"][0]["data"][0]["rowData"][0]["values"][0]["dataValidation"]
        cond = dv["condition"]
        jenis, nilai = cond.get("type"), cond.get("values", [])
        if jenis == "ONE_OF_LIST":
            return [v["userEnteredValue"] for v in nilai if v.get("userEnteredValue")]
        if jenis == "ONE_OF_RANGE" and nilai:
            rng = nilai[0]["userEnteredValue"].lstrip("=").replace("$", "")
            if "!" not in rng:
                rng = f"{q(tab)}!{rng}"
            r = svc.spreadsheets().values().get(
                spreadsheetId=sheet_id, range=rng, valueRenderOption="FORMATTED_VALUE").execute()
            return [str(x).strip() for row in r.get("values", []) for x in row if not kosong(x)]
    except Exception:
        return None
    return None


def pilih_opsi(opsi, pilihan, default_kata=None):
    """Cocokkan 'pilihan' ke salah satu opsi dropdown (abaikan emoji/huruf besar). Return opsi persis, atau None."""
    p = norm(pilihan) if pilihan else ""
    if p:
        for o in opsi:
            if norm(o) == p:
                return o
        for o in opsi:
            if p in norm(o) or (norm(o) and norm(o) in p):
                return o
    if default_kata:
        for o in opsi:
            if default_kata in norm(o):
                return o
    return None
