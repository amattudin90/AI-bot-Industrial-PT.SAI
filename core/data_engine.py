from pathlib import Path
from io import BytesIO
import math
import pandas as pd

class FactoryData:
    def __init__(self):
        self.v1 = {}
        self.v2_sum = None
        self.model_cells = None
        self.v1_context = ""
        self.v2_context = ""
        self.custom_sheets = {}      # Menyimpan sheet dari file upload dinamis
        self.custom_context = ""     # Konteks ekstra untuk AI Gemini
        self.diagnostics = []

    @staticmethod
    def _source(source):
        if hasattr(source, "seek"):
            source.seek(0)
        return source

    def parse_clean_sheet(self, source, sheet_name):
        try:
            self._source(source)
            raw = pd.read_excel(source, sheet_name=sheet_name, header=None)
            header_idx = 0
            for idx, row in raw.iterrows():
                text = " ".join(str(v).upper() for v in row.values if pd.notna(v))
                if any(k in text for k in ["MODEL", "BUILDING", "PROSES", "COMPONENT", "SECTION"]):
                    header_idx = idx
                    break
            self._source(source)
            df = pd.read_excel(source, sheet_name=sheet_name, skiprows=header_idx)
            df = df.dropna(how="all").reset_index(drop=True)
            return df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")]
        except Exception as exc:
            self.diagnostics.append(f"V1 sheet {sheet_name}: {exc}")
            return None

    def parse_v2_sum(self, source):
        try:
            self._source(source)
            xls = pd.ExcelFile(source)
            sum_sheet = next((s for s in xls.sheet_names if s.strip().upper() == "SUM"), None)
            if not sum_sheet:
                self.diagnostics.append("V2: sheet SUM tidak ditemukan.")
                return None
            self._source(source)
            raw = pd.read_excel(source, sheet_name=sum_sheet, header=None)
            header_idx = None
            for idx, row in raw.iterrows():
                text = " ".join(str(v).upper() for v in row.values if pd.notna(v))
                if "SECTION" in text and "ITEM" in text:
                    header_idx = idx
                    break
            if header_idx is None:
                for idx, row in raw.iterrows():
                    text = " ".join(str(v).upper() for v in row.values if pd.notna(v))
                    if "SECTION" in text or "ITEM" in text:
                        header_idx = idx
                        break
            if header_idx is None:
                self.diagnostics.append("V2: header SUM tidak terdeteksi.")
                return None

            data_start = header_idx + 1
            while data_start < len(raw):
                row = raw.iloc[data_start]
                if row.isna().all():
                    data_start += 1
                    continue
                text = " ".join(str(v).upper() for v in row.values if pd.notna(v))
                if "WK 27" in text and "AVG" in text:
                    data_start += 1
                    continue
                break

            cols = ["NO","SECTION","Working Hour","Item","WK 27","WK 28","WK 29","WK 30","WK 31","AVG","Action Plan"]
            df = raw.iloc[data_start:, :len(cols)].copy()
            if df.shape[1] < len(cols):
                self.diagnostics.append("V2: jumlah kolom SUM kurang dari struktur yang diharapkan.")
                return None
            df.columns = cols
            df = df.dropna(how="all").reset_index(drop=True)
            for col in ["NO","SECTION","Working Hour"]:
                df[col] = df[col].ffill()
            for col in ["WK 27","WK 28","WK 29","WK 30","WK 31","AVG"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            
            # Bersihkan baris header ganda / kosong
            df = df.dropna(subset=["SECTION"]).reset_index(drop=True)
            return df
        except Exception as exc:
            self.diagnostics.append(f"V2 SUM: {exc}")
            return None

    def parse_model_cell_sheet(self, source, sheet_name):
        known = {"BUILDING","CELL","MODEL","GND","WIDTH","COMPONENT","QTY"}
        try:
            self._source(source)
            raw = pd.read_excel(source, sheet_name=sheet_name, header=None)
            header_idx = None
            for idx, row in raw.iterrows():
                vals = {str(v).strip().upper() for v in row.values[:8] if pd.notna(v)}
                if {"BUILDING","CELL","MODEL"}.issubset(vals):
                    header_idx = idx
                    break
            if header_idx is None:
                return None
            header = raw.iloc[header_idx]
            end_col = 0
            for i, value in enumerate(header):
                if pd.isna(value) or str(value).strip().upper() not in known:
                    break
                end_col = i
            cols = [str(c).strip() for c in header.iloc[:end_col+1]]
            data = raw.iloc[header_idx+1:, :end_col+1].copy()
            data.columns = cols
            if "Building" in data.columns: data["Building"] = data["Building"].ffill()
            if "Cell" in data.columns: data["Cell"] = data["Cell"].ffill()
            if "Model" not in data.columns: return None
            data = data.dropna(subset=["Model"])
            data["Section"] = sheet_name
            return data.reset_index(drop=True)
        except Exception as exc:
            self.diagnostics.append(f"Model/Cell {sheet_name}: {exc}")
            return None

    def load_dynamic_file(self, file_source):
        """Membaca SELURUH sheet dari file upload rumit tanpa batasan model tertentu."""
        try:
            self._source(file_source)
            xls = pd.ExcelFile(file_source)
            self.custom_sheets = {}
            snippets = []

            for sheet in xls.sheet_names:
                self._source(file_source)
                df = pd.read_excel(file_source, sheet_name=sheet)
                df_clean = df.dropna(how="all").dropna(axis=1, how="all")
                if not df_clean.empty:
                    self.custom_sheets[sheet] = df_clean
                    
                    # Ambil baris sampel dari tiap sheet secara utuh
                    snippet_text = f"--- DYNAMIC SHEET [{sheet}] (Total {len(df_clean)} baris, {len(df_clean.columns)} kolom) ---\n"
                    snippet_text += df_clean.head(30).to_string(index=False)
                    snippets.append(snippet_text)

            self.custom_context = "\n\n".join(snippets)
        except Exception as exc:
            self.diagnostics.append(f"Dynamic File Error: {exc}")

    def compact_context(self, max_chars=120000):
        """Membangun konteks universal untuk SELURUH model dan sheet yang ada di sistem."""
        # Ekstrak seluruh daftar sheet dinamis yang berhasil dimuat
        available_sheets = list(self.custom_sheets.keys())
        
        text = (
            "=== FACTORY DATA / SOURCE OF TRUTH ===\n"
            f"SUMMARY CAPACITY LOADED SHEETS ({len(available_sheets)} Sheets): {', '.join(available_sheets)}\n\n"
            "V1 BASELINE OVERVIEW:\n" + self.v1_context +
            "\n\nV2 CONTROL TOWER OVERVIEW:\n" + self.v2_context +
            "\n\nKNOWLEDGE BASE / ACCUMULATED CAPACITY DATA:\n" + self.custom_context +
            "\n\nDETERMINISTIC METRICS:\n" + str(self.metrics())
        )
        return text[:max_chars]

    def load(self, v1_source=None, v2_source=None):
        self.v1 = {}
        self.v2_sum = None
        self.model_cells = None
        self.v1_context = ""
        self.v2_context = ""
        self.custom_sheets = {}
        self.custom_context = ""

        if v1_source is not None:
            self._source(v1_source)
            try:
                xls_v1 = pd.ExcelFile(v1_source)
                for sheet in xls_v1.sheet_names:
                    df = self.parse_clean_sheet(v1_source, sheet)
                    if df is not None and not df.empty:
                        self.v1[sheet] = df
                self.v1_context = "\n\n".join(
                    f"SHEET [{name}]:\n{df.head(50).to_string(index=False)}"
                    for name, df in self.v1.items()
                )
            except Exception as exc:
                self.diagnostics.append(f"Gagal memuat V1: {exc}")

        if v2_source is not None:
            self._source(v2_source)
            try:
                xls_v2 = pd.ExcelFile(v2_source)
                has_sum = any(s.strip().upper() == "SUM" for s in xls_v2.sheet_names)
                
                if has_sum:
                    self.v2_sum = self.parse_v2_sum(v2_source)
                    frames = []
                    for sheet in xls_v2.sheet_names:
                        if sheet.strip().upper() == "SUM":
                            continue
                        df = self.parse_model_cell_sheet(v2_source, sheet)
                        if df is not None and not df.empty:
                            frames.append(df)
                    if frames:
                        self.model_cells = pd.concat(frames, ignore_index=True, sort=False)
                        lines = []
                        for _, row in self.model_cells.iterrows():
                            parts = [str(row.get("Section",""))]
                            for key in ["Building","Cell","Model","Gnd","QTY"]:
                                if key in row and pd.notna(row[key]):
                                    parts.append(f"{key} {row[key]}")
                            lines.append(" | ".join(parts))
                        model_text = "\n".join(lines)
                    else:
                        model_text = ""
                    sum_text = self.v2_sum.to_string(index=False) if self.v2_sum is not None else ""
                    self.v2_context = f"SUM SHEET:\n{sum_text}\n\nDETAIL CELL & MODEL:\n{model_text}"
                else:
                    self.load_dynamic_file(v2_source)
            except Exception as exc:
                self.diagnostics.append(f"Gagal memuat V2: {exc}")

    def metrics(self):
        result = {
            "v1_processes": len(self.v1),
            "v1_rows": sum(len(df) for df in self.v1.values()),
            "v2_rows": 0,
            "shortage_rows": 0,
            "shortage_sections": [],
            "critical_min": None,
            "custom_sheets_count": len(self.custom_sheets)
        }
        if self.v2_sum is not None and not self.v2_sum.empty:
            weeks = ["WK 27","WK 28","WK 29","WK 30","WK 31"]
            valid_weeks = [w for w in weeks if w in self.v2_sum.columns]
            if valid_weeks:
                result["v2_rows"] = len(self.v2_sum)
                mins = self.v2_sum[valid_weeks].min(axis=1, skipna=True)
                result["shortage_rows"] = int((mins < 0).sum())
                if result["shortage_rows"]:
                    result["shortage_sections"] = sorted(
                        self.v2_sum.loc[mins < 0, "SECTION"].dropna().astype(str).unique().tolist()
                    )
                    result["critical_min"] = float(mins.min())
        return result

    def compact_context(self, max_chars=120000):
        text = (
            "=== FACTORY DATA / SOURCE OF TRUTH ===\n"
            "V1 BASELINE:\n" + self.v1_context +
            "\n\nV2 CONTROL TOWER:\n" + self.v2_context +
            "\n\nDYNAMIC FILE DATA:\n" + self.custom_context +
            "\n\nDETERMINISTIC METRICS:\n" + str(self.metrics())
        )
        return text[:max_chars]
    
    def load_all_history(self, history_dir_path):
        """Membaca SELURUH file Excel di folder history dan mengekstrak teks secara pintar."""
        history_path = Path(history_dir_path)
        if not history_path.exists():
            return

        all_snippets = []
        excel_files = sorted(list(history_path.glob("*.xlsx")) + list(history_path.glob("*.xls")))

        for file_path in excel_files:
            try:
                xls = pd.ExcelFile(file_path)
                file_snippet = f"=== FILE MEMORI KNOWLEDGE BASE: {file_path.name} ===\n"
                
                for sheet in xls.sheet_names:
                    # Read tanpa header agar semua teks/baris/kolom terbaca utuh
                    df_raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
                    df_clean = df_raw.dropna(how="all").dropna(axis=1, how="all")
                    
                    if not df_clean.empty:
                        self.custom_sheets[f"{file_path.stem}_{sheet}"] = df_clean
                        
                        # Ubah seluruh isi sel menjadi string mentah tanpa terpotong header
                        raw_text_lines = []
                        for idx, row in df_clean.iterrows():
                            row_vals = [str(v).strip() for v in row.values if pd.notna(v) and str(v).strip() != "nan"]
                            if row_vals:
                                raw_text_lines.append(" | ".join(row_vals))
                        
                        sheet_content = "\n".join(raw_text_lines[:80]) # Ambil 80 baris teratas
                        file_snippet += f"--- Sheet [{sheet}] ({len(df_clean)} baris) ---\n{sheet_content}\n\n"
                
                all_snippets.append(file_snippet)
            except Exception as exc:
                self.diagnostics.append(f"Gagal membaca history file {file_path.name}: {exc}")

        self.custom_context = "\n\n".join(all_snippets)