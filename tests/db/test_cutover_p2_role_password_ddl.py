"""Composicao segura da clausula PASSWORD em CREATE ROLE / ALTER ROLE
(scripts/cutover-p2.ps1).

Bug real observado no Windows: o PostgreSQL rejeita bind parameter
($1 / %s via psycopg) na clausula PASSWORD de CREATE ROLE / ALTER ROLE
("syntax error at or near \"$1\""). Sao utility statements do
PostgreSQL, nao statements comuns -- nao aceitam parametro nessa
posicao. A correcao usa `sql.Literal(role_password)` (psycopg.sql),
que embute o valor como um literal SQL corretamente escapado/quoted --
nao e concatenacao manual, nao e f-string, nao e quoting manual.

Este teste NAO EXECUTA o script -- apenas le o texto bruto do .ps1 e
verifica estruturalmente:
- nem CREATE ROLE nem ALTER ROLE usam mais "PASSWORD %s";
- ambos usam sql.Literal(role_password) para a senha;
- o nome da role continua via sql.Identifier(role_name) (nao mudou);
- o bloco except de cada snippet sanitiza a mensagem de erro (nunca
  deixa a senha vazar via stdout/relatorio, mesmo que o driver ecoe a
  query na excecao).
"""

import re
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cutover-p2.ps1"


def _read_script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def _write_step_and_stop_cutover_detail_blocks(text: str):
    blocks = []
    for m in re.finditer(r"-(?:Detail|Extra)\s+@\{", text):
        start = m.end() - 1
        depth = 0
        i = start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start:i + 1])
                    break
            i += 1
    return blocks


class CutoverP2RolePasswordDdlTests(unittest.TestCase):
    """Prova estrutural: PASSWORD via sql.Literal, nunca via bind parameter."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read_script_text()

    def test_create_role_does_not_use_password_bind_parameter(self):
        self.assertNotIn(
            'PASSWORD %s',
            self.text,
            "CREATE ROLE/ALTER ROLE nao devem mais usar 'PASSWORD %s' "
            "(bind parameter) -- o PostgreSQL rejeita isso na clausula "
            "PASSWORD de utility statements ('syntax error at or near "
            "\"$1\"', erro real observado no Windows).",
        )

    def test_create_role_uses_sql_literal_for_password(self):
        self.assertIn(
            'sql.SQL(\n                "CREATE ROLE {} LOGIN PASSWORD {} NOCREATEDB NOCREATEROLE NOSUPERUSER NOREPLICATION"\n            ).format(\n                sql.Identifier(role_name),\n                sql.Literal(role_password),\n            )',
            self.text,
            "CREATE ROLE deve compor a senha com sql.Literal(role_password), "
            "mantendo sql.Identifier(role_name) para o nome da role.",
        )

    def test_alter_role_uses_sql_literal_for_password(self):
        self.assertIn(
            'sql.SQL(\n                "ALTER ROLE {} WITH PASSWORD {}"\n            ).format(\n                sql.Identifier(role_name),\n                sql.Literal(role_password),\n            )',
            self.text,
            "ALTER ROLE deve compor a senha com sql.Literal(role_password), "
            "mantendo sql.Identifier(role_name) para o nome da role.",
        )

    def test_no_manual_string_concatenation_or_fstring_with_password(self):
        # Nenhuma linha deve montar a query concatenando/interpolando a
        # senha diretamente numa f-string ou com + de strings.
        unsafe_patterns = [
            re.compile(r'f["\'].*\{role_password\}'),
            re.compile(r'["\']?\s*\+\s*role_password\s*\+'),
        ]
        for pattern in unsafe_patterns:
            match = pattern.search(self.text)
            self.assertIsNone(
                match,
                f"encontrada possivel concatenacao/f-string insegura com "
                f"role_password: {match}",
            )

    def test_exception_handlers_sanitize_password_before_printing(self):
        # Cada bloco except que lida com CREATE ROLE / ALTER ROLE deve
        # sanitizar a mensagem antes de print(json.dumps(...)) -- nunca
        # deixar a senha vazar via stdout (que e capturado e pode ir
        # parar em Stop-Cutover/Save-Report).
        occurrences = re.findall(
            r'\.replace\(role_password, "\[REDACTED\]"\)', self.text
        )
        self.assertEqual(
            len(occurrences),
            2,
            "esperado exatamente 2 ocorrencias de sanitizacao "
            ".replace(role_password, \"[REDACTED]\") -- uma no except "
            "do CREATE ROLE, outra no do ALTER ROLE.",
        )

    def test_no_secret_variable_appears_in_report_detail_blocks(self):
        blocks = _write_step_and_stop_cutover_detail_blocks(self.text)
        self.assertGreater(len(blocks), 0)
        secret_vars = (
            "$recoveryPassword",
            "$finalPassword",
            "$dbUrlToWrite",
            "$generatedPassword",
            "$JarvisAppPassword",
            "$AdminConnectionString",
        )
        offenders = []
        for block in blocks:
            for secret_var in secret_vars:
                if secret_var in block:
                    offenders.append((secret_var, block))
        self.assertEqual(
            offenders,
            [],
            f"variavel de segredo encontrada dentro de um bloco "
            f"-Detail/-Extra: {offenders}",
        )

    def test_role_name_still_uses_sql_identifier(self):
        self.assertEqual(
            self.text.count("sql.Identifier(role_name)"),
            2,
            "sql.Identifier(role_name) deve continuar presente exatamente "
            "2 vezes (CREATE ROLE e ALTER ROLE) -- o nome da role nao "
            "mudou de mecanismo de composicao.",
        )


if __name__ == "__main__":
    unittest.main()
