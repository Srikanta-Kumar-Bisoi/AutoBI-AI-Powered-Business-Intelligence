from io import BytesIO
import unittest

import pandas as pd
from openpyxl import load_workbook
from starlette.datastructures import UploadFile

from app.cleaning import (
    clean_dataframe,
    dataframe_preview,
    prepare_excel_export,
    standardize_column_names,
    summarize_dataframe,
)
from app.main import read_dataset


class CleaningTests(unittest.TestCase):
    def test_keep_is_default_and_does_not_mutate_input(self):
        source = pd.DataFrame({"amount": [1.0, None], "city": ["Oslo", None]})

        cleaned = clean_dataframe(source)

        self.assertTrue(cleaned.equals(source))
        self.assertEqual(summarize_dataframe(cleaned)["missing_cells"], 2)
        self.assertEqual(summarize_dataframe(source)["missing_cells"], 2)

    def test_mean_fills_numeric_columns_only(self):
        source = pd.DataFrame(
            {
                "amount": [2.0, None, 4.0],
                "category": ["north", None, "south"],
                "active": [True, None, False],
            }
        )

        cleaned = clean_dataframe(source, missing_strategy="mean")

        self.assertEqual(cleaned["amount"].iloc[1], 3.0)
        self.assertTrue(pd.api.types.is_numeric_dtype(cleaned["amount"].dtype))
        self.assertTrue(pd.isna(cleaned["category"].iloc[1]))
        self.assertTrue(pd.isna(cleaned["active"].iloc[1]))
        self.assertEqual(summarize_dataframe(cleaned)["missing_cells"], 2)

    def test_median_fills_nullable_integer_without_losing_original_values(self):
        exact_large_integer = 2**60
        source = pd.DataFrame(
            {
                "id": pd.Series(
                    [exact_large_integer, pd.NA, exact_large_integer + 2],
                    dtype="Int64",
                )
            }
        )

        cleaned = clean_dataframe(source, missing_strategy="median")

        self.assertEqual(cleaned["id"].iloc[0], exact_large_integer)
        self.assertEqual(cleaned["id"].iloc[1], exact_large_integer + 1)
        self.assertEqual(cleaned["id"].iloc[2], exact_large_integer + 2)
        self.assertEqual(str(cleaned["id"].dtype), "Int64")

    def test_fractional_integer_mean_stays_numeric_when_values_are_safe(self):
        source = pd.DataFrame(
            {"amount": pd.Series([1, pd.NA, 2], dtype="Int64")}
        )

        cleaned = clean_dataframe(source, missing_strategy="mean")

        self.assertEqual(cleaned["amount"].iloc[1], 1.5)
        self.assertTrue(pd.api.types.is_numeric_dtype(cleaned["amount"].dtype))
        self.assertTrue(pd.isna(source["amount"].iloc[1]))

    def test_mode_fills_text_but_leaves_numeric_and_date_columns(self):
        source = pd.DataFrame(
            {
                "label": ["east", "east", None],
                "amount": [1.0, None, 3.0],
                "when": pd.to_datetime(["2025-01-01", None, "2025-01-03"]),
            }
        )

        cleaned = clean_dataframe(source, missing_strategy="mode")

        self.assertEqual(cleaned["label"].iloc[2], "east")
        self.assertTrue(pd.isna(cleaned["amount"].iloc[1]))
        self.assertTrue(pd.isna(cleaned["when"].iloc[1]))

    def test_drop_rows_and_duplicate_removal_are_independent_options(self):
        source = pd.DataFrame(
            {"id": [1, 2, 2, 3], "value": ["a", None, None, "d"]}
        )

        cleaned = clean_dataframe(
            source,
            missing_strategy="drop_rows",
            remove_duplicates=True,
        )

        self.assertEqual(cleaned.to_dict("records"), [{"id": 1, "value": "a"}, {"id": 3, "value": "d"}])

    def test_column_standardization_is_opt_in_and_resolves_collisions(self):
        columns = ["Order Date", "order-date", "  ", "Order Date"]

        self.assertEqual(
            standardize_column_names(columns),
            ["order_date", "order_date_2", "column", "order_date_3"],
        )
        source = pd.DataFrame([[1, 2]], columns=["Order Date", "Customer Name"])
        cleaned = clean_dataframe(source, standardize_columns=True)

        self.assertEqual(list(cleaned.columns), ["order_date", "customer_name"])
        self.assertEqual(source.columns.tolist(), ["Order Date", "Customer Name"])

    def test_preview_preserves_duplicate_headers_and_large_integer_display(self):
        large_integer = 2**60
        frame = pd.DataFrame([[large_integer, None]], columns=["id", "id"])

        preview = dataframe_preview(frame)

        self.assertEqual(preview["columns"], ["id", "id"])
        self.assertEqual(preview["rows"], [[str(large_integer), None]])

    def test_csv_parser_keeps_large_integers_exact_when_other_rows_are_missing(self):
        first_id = 2**60 + 1
        content = f"id,label\n{first_id},a\n,b\n{first_id + 2},c\n".encode()
        upload = UploadFile(filename="ids.csv", file=BytesIO(content))

        frame, _ = read_dataset(upload)

        self.assertEqual(str(frame["id"].dtype), "Int64")
        self.assertEqual(frame["id"].iloc[0], first_id)
        self.assertTrue(pd.isna(frame["id"].iloc[1]))
        self.assertEqual(frame["id"].iloc[2], first_id + 2)

    def test_excel_export_keeps_large_integer_digits_as_text(self):
        large_integer = 2**60 + 1
        source = pd.DataFrame(
            {"id": pd.Series([large_integer, pd.NA], dtype="Int64")}
        )
        export = prepare_excel_export(source)
        workbook_bytes = BytesIO()
        export.to_excel(workbook_bytes, index=False, engine="openpyxl")
        workbook = load_workbook(
            BytesIO(workbook_bytes.getvalue()), read_only=True, data_only=True
        )

        self.assertEqual(workbook.active["A2"].value, str(large_integer))
        self.assertEqual(source["id"].iloc[0], large_integer)

    def test_invalid_missing_strategy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported missing-value strategy"):
            clean_dataframe(pd.DataFrame({"value": [1]}), missing_strategy="guess")


if __name__ == "__main__":
    unittest.main()
