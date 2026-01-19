# src/pipelines/export_csv.py
import os
import pandas as pd

def save_places_csv(rows: list[dict], out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out_path
