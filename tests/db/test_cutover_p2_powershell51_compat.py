"""Compatibilidade com Windows PowerShell 5.1 / .NET Framework em
scripts/cutover-p2.ps1.

Contexto: rodado de verdade no Windows, o cutover falhou apos
"4_check_existing_objects" (antes do STEP 5) com o erro real do .NET:

    [System.Security.Cryptography.RandomNumberGenerator] nao contem um
    metodo denominado 'Fill'.

`RandomNumberGenerator.Fill(Span<byte>)` e um metodo estatico introduzido
no .NET Core/5+ (via System.Security.Cryptography, assinatura baseada em
Span<T>) -- nao existe no .NET Framework 4.x, que e o runtime usado pelo
Windows PowerShell 5.1. O runtime PowerShell 5.1 real so tem o padrao
classico: `RandomNumberGenerator.Create()` (fabrica uma instancia
IDisposable) + `.GetBytes(byte[])` (instancia) + `.Dispose()`.

Este teste NAO EXECUTA o script -- apenas le o texto bruto do arquivo
.ps1 (como dado) e confirma, estruturalmente, que o metodo estatico
incompativel nao aparece mais em lugar nenhum, e que o padrao
Create()/GetBytes()/Dispose() esta presente exatamente onde antes
estava o ::Fill(...), preservando a mesma quantidade de bytes (32) e a
mesma transformacao downstream (Base64 + remocao de '+/=').
"""

import re
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cutover-p2.ps1"


def _read_script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


class CutoverP2PowerShell51CompatTests(unittest.TestCase):
    """Prova estrutural: RandomNumberGenerator.Fill nao pode permanecer."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read_script_text()

    def test_no_incompatible_random_number_generator_fill(self):
        matches = re.findall(r"RandomNumberGenerator\]::Fill\(", self.text)
        self.assertEqual(
            len(matches),
            0,
            "RandomNumberGenerator.Fill(...) e um metodo estatico do "
            ".NET Core/5+ (assinatura Span<byte>), incompativel com o "
            ".NET Framework 4.x usado pelo Windows PowerShell 5.1 real "
            "(erro observado: \"nao contem um metodo denominado "
            "'Fill'\"). Deve ser substituido por "
            "Create()/GetBytes()/Dispose().",
        )

    def test_create_get_bytes_dispose_pattern_present_for_each_random_password(self):
        # Duas geracoes de senha aleatoria no script: STEP 5 (criacao da
        # role) e STEP 9 (recovery via ALTER ROLE). Cada uma deve ter seu
        # proprio par Create()/GetBytes()/Dispose(), usando byte[32].
        create_calls = re.findall(
            r"RandomNumberGenerator\]::Create\(\)", self.text
        )
        self.assertEqual(
            len(create_calls),
            2,
            "esperado exatamente 2 usos de "
            "RandomNumberGenerator.Create() (STEP 5 e o recovery do "
            "STEP 9), um cada.",
        )
        get_bytes_calls = re.findall(r"\.GetBytes\(\$\w+\)", self.text)
        self.assertEqual(
            len(get_bytes_calls),
            2,
            "esperado exatamente 2 chamadas .GetBytes($algumaVariavel) "
            "(uma para cada geracao de senha aleatoria).",
        )
        dispose_calls = re.findall(r"\.Dispose\(\)", self.text)
        self.assertGreaterEqual(
            len(dispose_calls),
            2,
            "cada instancia de RandomNumberGenerator criada via "
            "Create() deve ser descartada explicitamente com "
            ".Dispose() (idealmente num bloco finally).",
        )

    def test_byte_array_size_preserved_at_32(self):
        # A quantidade de bytes aleatorios (32) nao pode ter mudado --
        # isso alteraria a entropia da senha gerada.
        size_declarations = re.findall(
            r"New-Object byte\[\] (\d+)", self.text
        )
        self.assertTrue(
            len(size_declarations) >= 2,
            "esperado pelo menos 2 declaracoes 'New-Object byte[] N' "
            "(uma para cada geracao de senha aleatoria).",
        )
        for size in size_declarations:
            self.assertEqual(
                size,
                "32",
                "o tamanho do array de bytes aleatorios nao pode ter "
                "mudado (era 32) -- isso enfraqueceria a entropia da "
                "senha gerada.",
            )

    def test_base64_sanitization_transformation_preserved(self):
        # A mesma transformacao downstream (Base64 + remocao de
        # caracteres '+/=' para deixar a senha "URL/shell-safe") deve
        # continuar presente, inalterada, para cada senha gerada.
        transform_occurrences = re.findall(
            r"\[Convert\]::ToBase64String\(\$\w+\) -replace '\[\+/=\]', ''",
            self.text,
        )
        self.assertEqual(
            len(transform_occurrences),
            2,
            "a transformacao Base64 + remocao de '+/=' deve continuar "
            "identica para as duas senhas geradas (STEP 5 e recovery "
            "do STEP 9) -- nao deve ter sido enfraquecida nem "
            "removida.",
        )

    def test_bootstrap_and_guards_unaffected(self):
        # Regressao rapida: os textos-chave do bootstrap/guards nao
        # devem ter sido tocados por esta correcao bounded.
        for expected in (
            "CREATE ROLE",
            "CREATE DATABASE",
            "ALTER ROLE",
            "ROLE_ATTRIBUTES_DRIFT",
            "DATABASE_OWNER_DRIFT",
            "FORBIDDEN_ROLE_NAMES",
            "FORBIDDEN_DB_NAMES",
        ):
            self.assertIn(
                expected,
                self.text,
                f"'{expected}' deveria continuar presente -- esta "
                "correcao e bounded a RandomNumberGenerator.Fill, nao "
                "deve remover/alterar bootstrap/guards.",
            )


if __name__ == "__main__":
    unittest.main()
