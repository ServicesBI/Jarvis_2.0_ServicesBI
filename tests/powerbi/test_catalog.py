from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WORKSPACE_ID = "12345678-1234-5678-9234-567812345678"
REPORT_ID = "87654321-4321-4765-8765-876543210987"


def catalog_module():
    try:
        return importlib.import_module("app.powerbi.catalog")
    except ModuleNotFoundError as exc:
        raise AssertionError("app.powerbi.catalog ainda não foi implementado") from exc


def valid_document(*, reports: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "version": 1,
        "reports": reports
        if reports is not None
        else [
            {
                "local_file": "Dashboard Financeiro.pbix",
                "connection_id": "powerbi_conta_trabalho",
                "workspace_id": WORKSPACE_ID,
                "report_id": REPORT_ID,
                "publish_to_web_src": "https://app.powerbi.com/view?r=Exact%2BToken%3D&keep=1",
            }
        ],
    }


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.catalog_path = Path(self.temp_dir.name) / "reports.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_document(self, document: object) -> None:
        self.catalog_path.write_text(json.dumps(document), encoding="utf-8")


class CatalogPathTests(CatalogTestCase):
    def test_default_path_is_derived_from_localappdata(self) -> None:
        catalog = catalog_module()

        result = catalog.resolve_catalog_path(local_app_data=self.temp_dir.name)

        self.assertEqual(
            result,
            Path(self.temp_dir.name) / "ServicesBI_Jarvis" / "powerbi" / "reports.json",
        )

    def test_missing_localappdata_is_not_configured(self) -> None:
        catalog = catalog_module()
        with patch.dict(os.environ, {}, clear=True):
            result = catalog.load_catalog()

        self.assertEqual(result.status, "not_configured")
        self.assertEqual(result.error_code, "local_app_data_unavailable")
        self.assertIsNone(result.catalog)

    def test_missing_catalog_file_is_not_configured(self) -> None:
        result = catalog_module().load_catalog(self.catalog_path)

        self.assertEqual(result.status, "not_configured")
        self.assertEqual(result.error_code, "catalog_not_found")


class CatalogValidationTests(CatalogTestCase):
    def assert_invalid(self, document: object, error_code: str = "invalid_schema") -> None:
        self.write_document(document)
        result = catalog_module().load_catalog(self.catalog_path)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error_code, error_code)
        self.assertIsNone(result.catalog)

    def test_valid_catalog_is_loaded_and_uuids_are_canonical(self) -> None:
        document = valid_document()
        report = document["reports"][0]
        report["workspace_id"] = "{12345678-1234-5678-9234-567812345678}"
        self.write_document(document)

        result = catalog_module().load_catalog(self.catalog_path)

        self.assertEqual(result.status, "found")
        self.assertEqual(str(result.catalog.reports[0].workspace_id), WORKSPACE_ID)
        self.assertEqual(str(result.catalog.reports[0].report_id), REPORT_ID)
        self.assertEqual(
            result.catalog.reports[0].publish_to_web_src,
            "https://app.powerbi.com/view?r=Exact%2BToken%3D&keep=1",
        )

    def test_publish_to_web_is_optional_and_rejects_noncanonical_destinations(self) -> None:
        base = valid_document()["reports"][0]
        without_publish = dict(base)
        without_publish.pop("publish_to_web_src")
        self.write_document(valid_document(reports=[without_publish]))
        self.assertIsNone(catalog_module().load_catalog(self.catalog_path).catalog.reports[0].publish_to_web_src)

        for invalid in (
            "http://app.powerbi.com/view?r=x",
            "https://evil.example/view?r=x",
            "https://app.powerbi.com/groups/x/reports/y",
            "https://user:pass@app.powerbi.com/view?r=x",
        ):
            with self.subTest(invalid=invalid):
                self.assert_invalid(valid_document(reports=[{**base, "publish_to_web_src": invalid}]))

    def test_empty_catalog_is_valid(self) -> None:
        self.write_document(valid_document(reports=[]))

        result = catalog_module().load_catalog(self.catalog_path)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.catalog.reports, ())

    def test_invalid_json_fails_closed_without_exposing_content(self) -> None:
        sensitive = (
            "Bearer secret-token-should-not-leak password credential "
            "https://malicious.example/report"
        )
        self.catalog_path.write_text(
            '{"version": 1, "secret": "' + sensitive, encoding="utf-8"
        )

        result = catalog_module().load_catalog(self.catalog_path)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error_code, "invalid_json")
        for marker in ("Bearer", "secret-token", "password", "credential", "https://"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, repr(result))
        self.assertNotIn(str(self.catalog_path), repr(result))

    def test_wrong_version_and_extra_fields_fail_closed(self) -> None:
        cases = [
            {"version": 2, "reports": []},
            {"version": 1.0, "reports": []},
            {"version": 1, "reports": [], "extra": True},
            valid_document(reports=[{**valid_document()["reports"][0], "extra": True}]),
        ]
        for document in cases:
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_invalid_uuid_and_connection_id_fail_closed(self) -> None:
        base = valid_document()["reports"][0]
        invalid_fields = {
            "workspace_id": ["not-a-uuid"],
            "report_id": ["not-a-uuid"],
            "connection_id": [
                "PowerBI",
                "-powerbi",
                "power bi",
                "a" * 161,
                "",
            ],
        }
        for field, values in invalid_fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_invalid(valid_document(reports=[{**base, field: value}]))

    def test_only_simple_pbix_filenames_are_accepted(self) -> None:
        base = valid_document()["reports"][0]
        invalid_names = [
            "report.xlsx",
            "report.pbix.exe",
            "folder/report.pbix",
            r"folder\report.pbix",
            r"C:\report.pbix",
            r"\\server\share\report.pbix",
            r"\\?\UNC\server\share\report.pbix",
            r"\\?\C:\report.pbix",
            "..",
            "report..pbix",
            ".pbix",
            " report.pbix",
        ]
        for name in invalid_names:
            with self.subTest(name=name):
                self.assert_invalid(valid_document(reports=[{**base, "local_file": name}]))

    def test_pbix_extension_is_case_insensitive(self) -> None:
        base = valid_document()["reports"][0]
        self.write_document(valid_document(reports=[{**base, "local_file": "Report.PBIX"}]))

        result = catalog_module().load_catalog(self.catalog_path)

        self.assertEqual(result.status, "found")
        self.assertEqual(result.catalog.reports[0].local_file, "Report.PBIX")

    def test_casefold_duplicate_invalidates_the_whole_catalog(self) -> None:
        base = valid_document()["reports"][0]
        self.assert_invalid(
            valid_document(
                reports=[
                    {**base, "local_file": "Financeiro.pbix"},
                    {**base, "local_file": "FINANCEIRO.PBIX", "report_id": WORKSPACE_ID},
                ]
            ),
            error_code="duplicate_local_file",
        )

    def test_catalog_read_is_bounded(self) -> None:
        catalog = catalog_module()
        encoded = json.dumps(valid_document(reports=[])).encode("utf-8")
        self.catalog_path.write_bytes(encoded + b" " * (catalog.MAX_CATALOG_BYTES - len(encoded)))
        self.assertEqual(catalog.load_catalog(self.catalog_path).status, "found")

        self.catalog_path.write_bytes(b" " * (catalog.MAX_CATALOG_BYTES + 1))
        result = catalog.load_catalog(self.catalog_path)
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error_code, "file_too_large")


class CatalogLookupTests(CatalogTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_document(valid_document())

    def test_lookup_finds_link_case_insensitively(self) -> None:
        result = catalog_module().find_report_link(
            "dashboard financeiro.PBIX", self.catalog_path
        )

        self.assertEqual(result.status, "found")
        self.assertEqual(result.link.connection_id, "powerbi_conta_trabalho")
        self.assertEqual(str(result.link.workspace_id), WORKSPACE_ID)
        self.assertEqual(str(result.link.report_id), REPORT_ID)

    def test_unknown_file_is_not_linked(self) -> None:
        result = catalog_module().find_report_link("Outro.pbix", self.catalog_path)

        self.assertEqual(result.status, "not_linked")
        self.assertIsNone(result.link)

    def test_missing_configuration_propagates_not_configured(self) -> None:
        missing = self.catalog_path.with_name("missing.json")
        result = catalog_module().find_report_link("Outro.pbix", missing)

        self.assertEqual(result.status, "not_configured")
        self.assertEqual(result.error_code, "catalog_not_found")

    def test_invalid_catalog_propagates_invalid_without_partial_lookup(self) -> None:
        self.catalog_path.write_text("not-json", encoding="utf-8")
        result = catalog_module().find_report_link(
            "Dashboard Financeiro.pbix", self.catalog_path
        )

        self.assertEqual(result.status, "invalid")
        self.assertIsNone(result.link)

    def test_invalid_lookup_name_fails_closed(self) -> None:
        result = catalog_module().find_report_link(r"C:\Dashboard.pbix", self.catalog_path)

        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.error_code, "invalid_lookup")
        self.assertIsNone(result.link)


if __name__ == "__main__":
    unittest.main()
