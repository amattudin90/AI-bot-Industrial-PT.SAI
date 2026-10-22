from pathlib import Path
import json
import re
import pandas as pd


class FactoryData:
    """Parser Excel pabrik + mesin metrik deterministik (bukan AI)."""

    DEFAULT_PLANNING = {
        "gross_hours": 10.0,
        "working_days": 22.5,
        "downtime_pct": 15.0,
        "allowance_pct": 15.0,
    }

    def __init__(self):
        self.v1 = {}
        self.v2_sum = None
        self.model_cells = None
        self.v1_context = ""
        self.v2_context = ""
        self.custom_sheets = {}
        self.custom_context = ""
        self.diagnostics = []
        self.planning = dict(self.DEFAULT_PLANNING)

    @staticmethod
    def _source(source):
        if hasattr(source, "seek"):
            source.seek(0)
        return source

    @staticmethod
    def _week_columns(df):
        cols = []
        for col in df.columns:
            match = re.match(r"(?i)^WK\s*(\d+)$", str(col).strip())
            if match:
                cols.append((int(match.group(1)), str(col).strip()))
        cols.sort(key=lambda item: item[0])
        return [name for _, name in cols]

    def set_planning_parameters(
        self,
        gross_hours=10.0,
        working_days=22.5,
        downtime_pct=15.0,
        allowance_pct=15.0,
    ):
        """Parameter IE dari UI. Tidak mengubah angka Excel mentah."""
        self.planning = {
            "gross_hours": float(gross_hours),
            "working_days": float(working_days),
            "downtime_pct": float(downtime_pct),
            "allowance_pct": float(allowance_pct),
        }
        return self.planning_capacity()

    def planning_capacity(self):
        """Waktu tersedia deterministik: net = gross × (1-DT) × (1-allowance)."""
        p = self.planning
        downtime = max(0.0, min(p["downtime_pct"], 100.0)) / 100.0
        allowance = max(0.0, min(p["allowance_pct"], 100.0)) / 100.0
        net_day = p["gross_hours"] * (1.0 - downtime) * (1.0 - allowance)
        return {
            "gross_hours_per_day": round(p["gross_hours"], 4),
            "working_days_per_month": round(p["working_days"], 4),
            "downtime_pct": round(p["downtime_pct"], 4),
            "allowance_pct": round(p["allowance_pct"], 4),
            "net_hours_per_day": round(net_day, 4),
            "available_hours_per_month": round(net_day * p["working_days"], 4),
            "note": (
                "Net hours are calculated from user parameters. "
                "Weekly Excel values are kept as FACT and are not rescaled."
            ),
        }

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

    def _normalize_sum_columns(self, columns):
        used = {}
        normalized = []
        for raw_name in columns:
            name = "" if raw_name is None else str(raw_name).strip()
            key = name.upper()
            week = re.match(r"^WK\s*(\d+)$", key)
            if week:
                name = f"WK {int(week.group(1))}"
            elif key == "SECTION":
                name = "SECTION"
            elif key in {"ITEM", "ITEMS"}:
                name = "Item"
            elif key in {"WORKING HOUR", "WORKING HOURS", "WH"}:
                name = "Working Hour"
            elif key in {"AVG", "AVERAGE"}:
                name = "AVG"
            elif key in {"ACTION PLAN", "ACTION"}:
                name = "Action Plan"
            elif key == "NO":
                name = "NO"
            elif not name:
                name = "col"
            if name in used:
                used[name] += 1
                name = f"{name}_{used[name]}"
            else:
                used[name] = 0
            normalized.append(name)
        return normalized

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

            header_vals = [
                "" if pd.isna(v) else str(v).strip()
                for v in raw.iloc[header_idx].tolist()
            ]
            while header_vals and header_vals[-1] == "":
                header_vals.pop()

            data_start = header_idx + 1
            while data_start < len(raw):
                row = raw.iloc[data_start]
                if row.isna().all():
                    data_start += 1
                    continue
                text = " ".join(str(v).upper() for v in row.values if pd.notna(v))
                if re.search(r"WK\s*\d+", text) and "AVG" in text and data_start == header_idx + 1:
                    data_start += 1
                    continue
                break

            fallback = [
                "NO", "SECTION", "Working Hour", "Item",
                "WK 27", "WK 28", "WK 29", "WK 30", "WK 31", "AVG", "Action Plan",
            ]
            has_week_header = any(re.match(r"(?i)^WK\s*\d+$", h) for h in header_vals)
            if has_week_header and len(header_vals) >= 4:
                cols = self._normalize_sum_columns(header_vals)
                df = raw.iloc[data_start:, :len(cols)].copy()
                df.columns = cols
            else:
                if raw.shape[1] < len(fallback):
                    self.diagnostics.append("V2: jumlah kolom SUM kurang dari struktur yang diharapkan.")
                    return None
                df = raw.iloc[data_start:, :len(fallback)].copy()
                df.columns = fallback

            df = df.dropna(how="all").reset_index(drop=True)
            for col in ["NO", "SECTION", "Working Hour"]:
                if col in df.columns:
                    df[col] = df[col].ffill()
            numeric_cols = self._week_columns(df)
            if "AVG" in df.columns:
                numeric_cols.append("AVG")
            if "Working Hour" in df.columns:
                numeric_cols.append("Working Hour")
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if "SECTION" not in df.columns:
                self.diagnostics.append("V2: kolom SECTION tidak ada setelah parse.")
                return None
            df = df.dropna(subset=["SECTION"]).reset_index(drop=True)
            return df
        except Exception as exc:
            self.diagnostics.append(f"V2 SUM: {exc}")
            return None

    def parse_model_cell_sheet(self, source, sheet_name):
        known = {"BUILDING", "CELL", "MODEL", "GND", "WIDTH", "COMPONENT", "QTY"}
        # Header di Excel bisa ditulis "MODEL", "Model", atau "model" tergantung
        # sheet-nya. Deteksi header di bawah sudah pakai .upper() jadi toleran
        # ke semua variasi itu, tapi versi lama mengambil nama kolom asli tanpa
        # normalisasi -> kalau header aslinya huruf besar semua, cek
        # `"Model" not in data.columns` di bawah selalu gagal dan sheet
        # ke-skip diam-diam. Sekarang nama kolom dinormalisasi dulu.
        label_map = {
            "BUILDING": "Building",
            "CELL": "Cell",
            "MODEL": "Model",
            "GND": "Gnd",
            "WIDTH": "Width",
            "COMPONENT": "Component",
            "QTY": "QTY",
        }
        try:
            self._source(source)
            raw = pd.read_excel(source, sheet_name=sheet_name, header=None)
            header_idx = None
            for idx, row in raw.iterrows():
                vals = {str(v).strip().upper() for v in row.values[:8] if pd.notna(v)}
                if {"BUILDING", "CELL", "MODEL"}.issubset(vals):
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
            cols = [
                label_map.get(str(c).strip().upper(), str(c).strip())
                for c in header.iloc[:end_col + 1]
            ]
            data = raw.iloc[header_idx + 1:, :end_col + 1].copy()
            data.columns = cols
            if "Building" in data.columns:
                data["Building"] = data["Building"].ffill()
            if "Cell" in data.columns:
                data["Cell"] = data["Cell"].ffill()
            if "Model" not in data.columns:
                self.diagnostics.append(
                    f"Model/Cell {sheet_name}: kolom Model tidak ditemukan setelah normalisasi header."
                )
                return None
            data = data.dropna(subset=["Model"])
            data["Section"] = sheet_name
            return data.reset_index(drop=True)
        except Exception as exc:
            self.diagnostics.append(f"Model/Cell {sheet_name}: {exc}")
            return None

    def load_dynamic_file(self, file_source):
        """Membaca seluruh sheet dari file tanpa asumsi layout V2 SUM."""
        try:
            self._source(file_source)
            xls = pd.ExcelFile(file_source)
            snippets = []

            for sheet in xls.sheet_names:
                self._source(file_source)
                df = pd.read_excel(file_source, sheet_name=sheet)
                df_clean = df.dropna(how="all").dropna(axis=1, how="all")
                if not df_clean.empty:
                    self.custom_sheets[sheet] = df_clean
                    snippet_text = (
                        f"--- DYNAMIC SHEET [{sheet}] "
                        f"(Total {len(df_clean)} baris, {len(df_clean.columns)} kolom) ---\n"
                    )
                    snippet_text += df_clean.head(30).to_string(index=False)
                    snippets.append(snippet_text)

            extra = "\n\n".join(snippets)
            if extra:
                if self.custom_context:
                    self.custom_context = extra + "\n\n" + self.custom_context
                else:
                    self.custom_context = extra
        except Exception as exc:
            self.diagnostics.append(f"Dynamic File Error: {exc}")

    def load(self, v1_source=None, v2_source=None):
        self.v1 = {}
        self.v2_sum = None
        self.model_cells = None
        self.v1_context = ""
        self.v2_context = ""
        self.custom_sheets = {}
        self.custom_context = ""
        self.diagnostics = []

        if v1_source is not None:
            self._source(v1_source)
            try:
                xls_v1 = pd.ExcelFile(v1_source)
                for sheet in xls_v1.sheet_names:
                    df = self.parse_clean_sheet(v1_source, sheet)
                    if df is not None and not df.empty:
                        self.v1[sheet] = df
                self.v1_context = "\n\n".join(
                    f"SHEET [{name}]:\n{df.head(30).to_string(index=False)}"
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
                            parts = [str(row.get("Section", ""))]
                            for key in ["Building", "Cell", "Model", "Gnd", "QTY"]:
                                if key in row and pd.notna(row[key]):
                                    parts.append(f"{key} {row[key]}")
                            lines.append(" | ".join(parts))
                        model_text = "\n".join(lines[:400])
                    else:
                        model_text = ""
                    sum_text = self.v2_sum.to_string(index=False) if self.v2_sum is not None else ""
                    self.v2_context = f"SUM SHEET:\n{sum_text}\n\nDETAIL CELL & MODEL:\n{model_text}"
                else:
                    self.load_dynamic_file(v2_source)
            except Exception as exc:
                self.diagnostics.append(f"Gagal memuat V2: {exc}")

    def _bottlenecks(self, df, week_cols, limit=10):
        if df is None or df.empty or not week_cols:
            return []
        work = df.copy()
        work["_worst"] = work[week_cols].min(axis=1, skipna=True)
        work = work.dropna(subset=["_worst"]).sort_values("_worst", ascending=True)
        rows = []
        for _, row in work.head(limit).iterrows():
            worst_week = None
            worst_val = row["_worst"]
            for week in week_cols:
                val = row.get(week)
                if pd.notna(val) and val == worst_val:
                    worst_week = week
                    break
            rows.append({
                "section": str(row.get("SECTION", "")),
                "item": str(row.get("Item", "") if pd.notna(row.get("Item")) else ""),
                "worst_week": worst_week,
                "worst_value": round(float(worst_val), 4),
                "avg": round(float(row["AVG"]), 4) if "AVG" in row and pd.notna(row.get("AVG")) else None,
                "is_shortage": bool(worst_val < 0),
            })
        return rows

    def metrics(self):
        planning = self.planning_capacity()
        result = {
            "v1_processes": len(self.v1),
            "v1_rows": int(sum(len(df) for df in self.v1.values())),
            "v2_rows": 0,
            "week_columns": [],
            "shortage_rows": 0,
            "shortage_sections": [],
            "shortage_by_section": {},
            "critical_min": None,
            "bottlenecks": [],
            "working_hour_vs_net": [],
            "custom_sheets_count": len(self.custom_sheets),
            "planning": planning,
        }
        if self.v2_sum is None or self.v2_sum.empty:
            return result

        week_cols = self._week_columns(self.v2_sum)
        result["week_columns"] = week_cols
        result["v2_rows"] = int(len(self.v2_sum))
        if not week_cols:
            return result

        mins = self.v2_sum[week_cols].min(axis=1, skipna=True)
        shortage_mask = mins < 0
        result["shortage_rows"] = int(shortage_mask.sum())
        if result["shortage_rows"]:
            shortage_df = self.v2_sum.loc[shortage_mask]
            sections = shortage_df["SECTION"].dropna().astype(str)
            result["shortage_sections"] = sorted(sections.unique().tolist())
            result["shortage_by_section"] = {
                section: int((sections == section).sum())
                for section in result["shortage_sections"]
            }
            result["critical_min"] = round(float(mins.min()), 4)

        result["bottlenecks"] = self._bottlenecks(self.v2_sum, week_cols)

        if "Working Hour" in self.v2_sum.columns:
            net = planning["net_hours_per_day"]
            seen = set()
            for _, row in self.v2_sum.iterrows():
                section = str(row.get("SECTION", "")).strip()
                if not section or section in seen:
                    continue
                wh = row.get("Working Hour")
                if pd.isna(wh):
                    continue
                seen.add(section)
                excel_wh = float(wh)
                result["working_hour_vs_net"].append({
                    "section": section,
                    "excel_working_hour": round(excel_wh, 4),
                    "net_hours_per_day": net,
                    "gap_hours_per_day": round(excel_wh - net, 4),
                    "excel_above_net": bool(excel_wh > net),
                })
        return result

    def compact_context(self, max_chars=120000):
        """Konteks AI: metrik deterministik dulu, Excel mentah belakangan."""
        metrics = self.metrics()
        available_sheets = list(self.custom_sheets.keys())
        header = (
            "=== FACTORY DATA / SOURCE OF TRUTH ===\n"
            "Python metrics below are FACT. Do not invent quantities.\n"
            f"KNOWLEDGE BASE SHEETS ({len(available_sheets)}): {', '.join(available_sheets[:80])}\n\n"
            "DETERMINISTIC METRICS (JSON):\n"
            + json.dumps(metrics, ensure_ascii=False, indent=2)
        )
        chunks = [
            header,
            "\n\nV2 CONTROL TOWER:\n" + (self.v2_context or "(not loaded)"),
            "\n\nV1 BASELINE:\n" + (self.v1_context or "(not loaded)"),
            "\n\nKNOWLEDGE BASE / ACCUMULATED CAPACITY DATA:\n" + (self.custom_context or "(empty)"),
        ]
        if self.diagnostics:
            chunks.append("\n\nPARSER DIAGNOSTICS:\n" + "\n".join(self.diagnostics[-20:]))

        text = ""
        for chunk in chunks:
            remaining = max_chars - len(text)
            if remaining <= 0:
                break
            text += chunk[:remaining]
        return text

    def load_all_history(self, history_dir_path):
        """Gabungkan seluruh Excel di folder history ke knowledge base."""
        history_path = Path(history_dir_path)
        if not history_path.exists():
            return

        all_snippets = [self.custom_context] if self.custom_context else []
        excel_files = sorted(
            list(history_path.glob("*.xlsx")) + list(history_path.glob("*.xls"))
        )

        for file_path in excel_files:
            try:
                xls = pd.ExcelFile(file_path)
                file_snippet = f"=== FILE MEMORI KNOWLEDGE BASE: {file_path.name} ===\n"

                for sheet in xls.sheet_names:
                    df_raw = pd.read_excel(file_path, sheet_name=sheet, header=None)
                    df_clean = df_raw.dropna(how="all").dropna(axis=1, how="all")
                    if df_clean.empty:
                        continue
                    self.custom_sheets[f"{file_path.stem}_{sheet}"] = df_clean
                    raw_text_lines = []
                    for _, row in df_clean.iterrows():
                        row_vals = [
                            str(v).strip()
                            for v in row.values
                            if pd.notna(v) and str(v).strip() not in {"", "nan"}
                        ]
                        if row_vals:
                            raw_text_lines.append(" | ".join(row_vals))
                    sheet_content = "\n".join(raw_text_lines[:80])
                    file_snippet += (
                        f"--- Sheet [{sheet}] ({len(df_clean)} baris) ---\n{sheet_content}\n\n"
                    )

                all_snippets.append(file_snippet)
            except Exception as exc:
                self.diagnostics.append(f"Gagal membaca history file {file_path.name}: {exc}")

        self.custom_context = "\n\n".join(all_snippets)