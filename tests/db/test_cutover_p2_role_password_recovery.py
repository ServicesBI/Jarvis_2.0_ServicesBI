"""Contrato de recuperacao deterministica da senha de jarvis_app quando o
bootstrap fica incompleto (scripts/cutover-p2.ps1).

Modulo: P2 OPERATIONAL CUTOVER -- correcao do bloqueador de credencial orfa
(aprovado pelo usuario).

Estes testes NAO EXECUTAM o script -- em nenhuma circunstancia -- e nao
tocam banco de dados, .env real, ou o Jarvis. Eles leem o texto bruto do
arquivo .ps1 (como dado) e verificam, estruturalmente, o contrato:

- Quando `jarvis_app` ja existe e ainda nao ha uma JARVIS_DATABASE_URL
  operacional valida/persistida, e uma -AdminConnectionString foi
  fornecida, o script deve conseguir redefinir deterministicamente a
  senha via `ALTER ROLE ... WITH PASSWORD %s` (query parametrizada via
  psycopg.sql, nunca por interpolacao insegura), sem precisar conhecer a
  senha antiga.
- Esse reset NUNCA acontece quando ja existe uma JARVIS_DATABASE_URL
  valida e reutilizavel (o ramo "existing_env_reused" sempre e avaliado
  antes, e retorna cedo).
- Atributos de uma role `jarvis_app` ja existente sao validados
  (rolcanlogin/rolsuper/rolcreatedb/rolcreaterole/rolreplication) --
  drift vira FAIL, nunca correcao automatica de privilegios.
- O owner de um database `jarvis` ja existente e validado -- drift vira
  FAIL, nunca ALTER DATABASE OWNER automatico.
- Nenhuma senha/segredo e escrito literalmente dentro de um bloco
  `-Detail @{ ... }` (o que iria parar no relatorio JSON via Write-Step).
- A logica original de criacao (CREATE ROLE / CREATE DATABASE) continua
  presente e intacta.
"""

import re
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cutover-p2.ps1"

STEP_HEADER_RE = re.compile(r"^# STEP (\d+)", re.MULTILINE)

SECRET_VARS = (
    "$recoveryPassword",
    "$finalPassword",
    "$dbUrlToWrite",
    "$generatedPassword",
    "$JarvisAppPassword",
    "$AdminConnectionString",
)


def _read_script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def _step_header_offsets(text: str) -> dict:
    offsets = {}
    for match in STEP_HEADER_RE.finditer(text):
        step_number = int(match.group(1))
        offsets.setdefault(step_number, match.start())
    return offsets


def _slice_step(text: str, offsets: dict, step_number: int, next_step_number: int) -> str:
    start = offsets[step_number]
    end = offsets[next_step_number]
    assert start < end, (
        f"STEP {step_number} deveria vir antes do STEP {next_step_number}."
    )
    return text[start:end]


def _write_step_and_stop_cutover_detail_blocks(text: str):
    """Extrai o texto de cada bloco `-Detail @{ ... }` / `-Extra @{ ... }`
    (hashtable literal de uma linha logica, ate o fechamento `}` que casa
    com a abertura), usado por Write-Step/Stop-Cutover para popular o
    relatorio JSON. Aproximacao textual: nao e um parser de PowerShell
    completo, mas suficiente para garantir que nenhuma variavel de
    segredo apareca como valor literal nesses blocos.
    """
    blocks = []
    for m in re.finditer(r"-(?:Detail|Extra)\s+@\{", text):
        start = m.end() - 1  # posicao do '{'
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


class CutoverP2RolePasswordRecoveryTests(unittest.TestCase):
    """Prova estrutural do contrato de recuperacao de senha (ALTER ROLE)."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read_script_text()
        cls.offsets = _step_header_offsets(cls.text)
        for required in (4, 9, 10):
            if required not in cls.offsets:
                raise AssertionError(
                    f"cabecalho '# STEP {required}' nao encontrado em "
                    f"{SCRIPT_PATH} -- script mudou de forma inesperada."
                )

    # -- Secao 2: validacao de objetos existentes -----------------------

    def test_role_attribute_validation_present_in_step4(self):
        step4 = _slice_step(self.text, self.offsets, 4, 5)
        for expected in (
            "rolcanlogin",
            "rolsuper",
            "rolcreatedb",
            "rolcreaterole",
            "rolreplication",
        ):
            self.assertIn(
                expected,
                step4,
                f"STEP 4 deve validar o atributo '{expected}' de uma role "
                "jarvis_app ja existente.",
            )
        self.assertIn(
            "ROLE_ATTRIBUTES_DRIFT",
            step4,
            "drift nos atributos de uma role jarvis_app existente deve "
            "produzir um blocker code explicito (FAIL), nunca correcao "
            "automatica de privilegios.",
        )

    def test_database_owner_validation_present_in_step4(self):
        step4 = _slice_step(self.text, self.offsets, 4, 5)
        self.assertIn(
            "DATABASE_OWNER_DRIFT",
            step4,
            "owner incorreto de um database jarvis ja existente deve "
            "produzir um blocker code explicito (FAIL), nunca ALTER "
            "DATABASE OWNER automatico.",
        )

    # -- Secao 3 (RED-driving): recovery de senha via ALTER ROLE --------

    def test_step9_contains_parameterized_alter_role(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        self.assertIn(
            "ALTER ROLE",
            step9,
            "STEP 9 deve conter um recovery de senha via ALTER ROLE para "
            "o cenario de role jarvis_app existente sem URL operacional "
            "valida ainda.",
        )
        self.assertIn(
            "sql.Identifier(role_name)",
            step9,
            "o ALTER ROLE deve usar sql.Identifier para o nome da role "
            "(nunca interpolacao de string insegura).",
        )
        # PostgreSQL rejeita bind parameter ($1/%s) na clausula PASSWORD
        # de ALTER ROLE (utility statement) -- a composicao segura correta
        # e sql.Literal(role_password), nao um parametro de cur.execute.
        self.assertIn(
            "sql.Literal(role_password)",
            step9,
            "a senha do ALTER ROLE deve ser composta com "
            "sql.Literal(role_password) (literal SQL corretamente "
            "escapado/quoted), nunca concatenada/interpolada manualmente "
            "nem passada como bind parameter (Postgres rejeita isso "
            "nesta clausula).",
        )

    def test_no_unsafe_string_interpolated_alter_role(self):
        # Nenhuma linha deve montar "ALTER ROLE ... PASSWORD" concatenando
        # diretamente uma variavel de senha do PowerShell dentro da string
        # (isso seria interpolacao insegura E vazaria a senha em texto
        # puro dentro do proprio arquivo de snippet temporario).
        unsafe_pattern = re.compile(
            r"ALTER ROLE[^\n]*\$(recoveryPassword|finalPassword|JarvisAppPassword|generatedPassword)"
        )
        match = unsafe_pattern.search(self.text)
        self.assertIsNone(
            match,
            f"ALTER ROLE parece interpolar uma senha diretamente na string: {match}",
        )

    def test_role_password_recovery_gated_on_admin_connection_string(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        # Ancora na invocacao SQL real (sql.SQL("ALTER ROLE {}"...), nao em
        # qualquer mencao textual de "ALTER ROLE" (que tambem pode aparecer
        # em comentarios explicativos antes do guard real).
        self.assertIn('sql.SQL(\n                "ALTER ROLE {} WITH PASSWORD {}"\n            )', step9)
        alter_offset = step9.index('sql.SQL(\n                "ALTER ROLE {} WITH PASSWORD {}"\n            )')
        window_start = max(0, alter_offset - 3000)
        preceding_window = step9[window_start:alter_offset]
        self.assertIn(
            "IsNullOrWhiteSpace($AdminConnectionString)",
            preceding_window,
            "o recovery via ALTER ROLE deve ser condicionado a presenca "
            "de -AdminConnectionString, verificado antes de tentar o "
            "reset.",
        )

    def test_recovery_not_reachable_before_existing_url_reuse_branch(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        self.assertIn("existing_env_reused", step9)
        self.assertIn("ALTER ROLE", step9)
        reused_offset = step9.index("existing_env_reused")
        alter_offset = step9.index("ALTER ROLE")
        self.assertLess(
            reused_offset,
            alter_offset,
            "o ramo que reaproveita uma JARVIS_DATABASE_URL ja valida "
            "deve aparecer (e ser avaliado/retornar) antes do bloco de "
            "recovery via ALTER ROLE -- o reset nunca deve ser alcancado "
            "quando ja existe uma URL operacional valida.",
        )

    def test_role_already_exists_without_admin_string_still_requires_password(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        self.assertIn(
            "JARVIS_APP_PASSWORD_REQUIRED",
            step9,
            "quando nao ha -AdminConnectionString (logo, nao ha recovery "
            "automatico possivel) e nao ha -JarvisAppPassword, o script "
            "deve continuar parando explicitamente (nunca prosseguir com "
            "uma senha desconhecida).",
        )

    # -- Secao 5: segredos nunca em relatorio/log ------------------------

    def test_no_secret_variable_appears_in_report_detail_blocks(self):
        blocks = _write_step_and_stop_cutover_detail_blocks(self.text)
        self.assertGreater(
            len(blocks), 0, "nenhum bloco -Detail/-Extra encontrado -- parsing quebrado?"
        )
        offenders = []
        for block in blocks:
            for secret_var in SECRET_VARS:
                if secret_var in block:
                    offenders.append((secret_var, block))
        self.assertEqual(
            offenders,
            [],
            f"variavel de segredo encontrada dentro de um bloco -Detail/-Extra "
            f"(iria parar no relatorio JSON via Write-Step/Stop-Cutover): {offenders}",
        )

    # -- Regressao: logica de criacao original permanece intacta ---------

    def test_create_role_and_create_database_blocks_still_present(self):
        step5_6_7 = _slice_step(self.text, self.offsets, 5, 8)
        self.assertIn("CREATE ROLE", step5_6_7)
        self.assertIn("CREATE DATABASE", step5_6_7)


if __name__ == "__main__":
    unittest.main()
