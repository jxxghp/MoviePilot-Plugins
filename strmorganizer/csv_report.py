# plugins/strmorganizer/csv_report.py

import csv
from pathlib import Path
from datetime import datetime


def write_csv(dirs, filename: str) -> Path:
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = filename.replace(".csv", f"_{now}.csv")

    base = Path("data/plugins")
    base.mkdir(parents=True, exist_ok=True)

    csv_path = base / name

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["缺失 STRM 的目录路径"])
        for d in dirs:
            writer.writerow([str(d)])

    return csv_path
