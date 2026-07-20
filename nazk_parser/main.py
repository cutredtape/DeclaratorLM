"""Entry point: download declarations from the open NAZK API v2.

Run from the nazk_parser directory:
  python main.py
  python main.py --limit 100 --save-dir dataset_declarations
  python main.py --user-declarant-id 3000099 --limit 500

List API parameters: https://public.nazk.gov.ua/public_api
"""

from __future__ import annotations

import argparse
import os
import sys

from nazk_download import download_professional_dataset


def _count_json(save_dir: str) -> int:
    if not os.path.exists(save_dir):
        return 0
    return len([f for f in os.listdir(save_dir) if f.endswith(".json")])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Завантаження декларацій з API НАЗК v2.")
    p.add_argument("--save-dir", default="dataset_declarations", help="Каталог для decl_<uuid>.json")
    p.add_argument("--limit", type=int, default=2000, help="Скільки нових файлів зберегти (всього в каталозі)")
    p.add_argument("--delay", type=float, default=1.5, help="Пауза між завантаженням документів (сек)")
    p.add_argument("--query", default="", help="Пошуковий запит (3–255 символів), параметр API query")
    p.add_argument(
        "--user-declarant-id",
        type=int,
        default=0,
        help="ID суб'єкта декларування (число), параметр API user_declarant_id",
    )
    p.add_argument("--declaration-year", type=int, default=0, help="Рік декларації, parameter declaration_year")
    p.add_argument("--declaration-type", type=int, default=0, help="Тип декларації 1–4, parameter declaration_type")
    p.add_argument("--document-type", type=int, default=0, help="Тип документа 1–3, parameter document_type")
    return p


def main() -> None:
    args = build_parser().parse_args()
    save_dir = args.save_dir
    limit = args.limit

    list_params: dict = {}
    if args.query.strip():
        list_params["query"] = args.query.strip()
    if args.user_declarant_id > 0:
        list_params["user_declarant_id"] = args.user_declarant_id
    if args.declaration_year > 0:
        list_params["declaration_year"] = args.declaration_year
    if args.declaration_type > 0:
        list_params["declaration_type"] = args.declaration_type
    if args.document_type > 0:
        list_params["document_type"] = args.document_type

    initial = _count_json(save_dir)
    print(f"Починаємо. Вже є: {initial}. Ціль (всього файлів): {limit}")
    if list_params:
        print(f"Фільтри списку API: {list_params}")

    n = download_professional_dataset(
        limit=limit,
        save_dir=save_dir,
        delay_sec=args.delay,
        list_params=list_params or None,
    )

    final = _count_json(save_dir)
    print(f"Завершено. Функція повернула saved count={n}, у каталозі JSON файлів: {final}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nПерервано користувачем.", file=sys.stderr)
        sys.exit(130)
