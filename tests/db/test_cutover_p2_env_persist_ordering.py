"""Contrato de ordenacao: persistencia de JARVIS_DATABASE_URL em .env
(scripts/cutover-p2.ps1) adiada do STEP 9 para o STEP 17.

Modulo: P2 CUTOVER -- CORRECAO DA JANELA DE RISCO (Alternativa A aprovada
pelo usuario).

Nao ha um test runner PowerShell disponivel neste ambiente de execucao.
Estes testes NAO EXECUTAM o script -- em nenhuma circunstancia, em
nenhum metodo -- e nao tocam banco de dados, .env real, ou o Jarvis.
Eles apenas leem o texto bruto do arquivo .ps1 (como dado) e verificam,
estruturalmente, o contrato de ordenacao aprovado:

- STEP 9 continua resolvendo/validando a JARVIS_DATABASE_URL e a
  exporta apenas no ambiente do processo ($env:JARVIS_DATABASE_URL),
  SEM persistir em disco (.env). Alembic (STEP 10) e migrate_task_state
  (STEP 12/15/16) continuam recebendo a URL via heranca de variavel de
  ambiente do processo filho -- nenhuma mudanca de codigo Python e
  necessaria para isso (get_setting() ja checa os.environ primeiro).
- A UNICA gravacao em disco (Set-Content -Path $EnvFile) do valor
  operacional acontece dentro do bloco do STEP 17, imediatamente antes
  do primeiro restart controlado (a primeira chamada efetiva a
  Start-JarvisProcess), ou seja, depois que schema (STEP 10), dry-run
  (STEP 12), import real (STEP 15) e idempotencia (STEP 16) ja foram
  aprovados.
- O ramo em que uma JARVIS_DATABASE_URL ja existente em .env e valida e
  reaproveitada ("existing_env_reused") nunca grava em disco (nao havia
  motivo para reescrever algo que ja estava correto, e isso continua
  valendo).
- Nao ha dual-write: existe exatamente um ponto de persistencia em todo
  o script.
"""

import re
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cutover-p2.ps1"

STEP_HEADER_RE = re.compile(r"^# STEP (\d+)", re.MULTILINE)


def _read_script_text() -> str:
    # utf-8-sig: le e descarta o BOM automaticamente, sem exigir que o
    # arquivo deixe de ser UTF-8-with-BOM (o encoding correto do script,
    # ja validado em turno anterior contra o parser nativo do Windows
    # PowerShell 5.1).
    return SCRIPT_PATH.read_text(encoding="utf-8-sig")


def _step_header_offsets(text: str) -> dict:
    """Mapa {numero_do_step: offset_de_inicio_do_cabecalho}."""
    offsets = {}
    for match in STEP_HEADER_RE.finditer(text):
        step_number = int(match.group(1))
        offsets.setdefault(step_number, match.start())
    return offsets


def _slice_step(text: str, offsets: dict, step_number: int, next_step_number: int) -> str:
    start = offsets[step_number]
    end = offsets[next_step_number]
    assert start < end, (
        f"STEP {step_number} deveria vir antes do STEP {next_step_number} "
        "no arquivo, mas os offsets nao confirmam isso -- script "
        "estruturalmente inesperado."
    )
    return text[start:end]


class CutoverP2EnvPersistOrderingTests(unittest.TestCase):
    """Prova estrutural do contrato de ordenacao da Alternativa A."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read_script_text()
        cls.offsets = _step_header_offsets(cls.text)
        for required in (9, 10, 12, 15, 16, 17, 18):
            if required not in cls.offsets:
                raise AssertionError(
                    f"cabecalho '# STEP {required}' nao encontrado em "
                    f"{SCRIPT_PATH} -- script mudou de forma inesperada."
                )

    def test_step9_sets_process_env_var(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        self.assertIn(
            "$env:JARVIS_DATABASE_URL = $dbUrlToWrite",
            step9,
            "STEP 9 deve continuar exportando JARVIS_DATABASE_URL no "
            "ambiente do processo, para Alembic/migrate_task_state "
            "herdarem via processo filho.",
        )

    def test_step9_does_not_persist_env_file(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        self.assertNotIn(
            "Set-Content -Path $EnvFile",
            step9,
            "STEP 9 nao deve mais gravar JARVIS_DATABASE_URL em disco "
            "(.env) -- essa e exatamente a janela de risco que a "
            "Alternativa A elimina (restart anterior ao STEP 17 nao "
            "pode mais ler do .env uma URL para schema/dados "
            "incompletos).",
        )

    def test_only_one_persistence_site_in_whole_script(self):
        occurrences = self.text.count("Set-Content -Path $EnvFile")
        self.assertEqual(
            occurrences,
            1,
            "deve haver exatamente um ponto de persistencia em disco de "
            "JARVIS_DATABASE_URL em todo o script (sem dual-write STEP "
            "9 + STEP 17 simultaneos).",
        )

    def test_persistence_happens_inside_step17_block(self):
        step17 = _slice_step(self.text, self.offsets, 17, 18)
        self.assertIn(
            "Set-Content -Path $EnvFile",
            step17,
            "a unica gravacao em disco deve estar dentro do bloco do "
            "STEP 17 (imediatamente antes do primeiro restart "
            "controlado), nao mais no STEP 9.",
        )

    def test_persistence_happens_before_first_controlled_restart(self):
        step17 = _slice_step(self.text, self.offsets, 17, 18)
        self.assertIn("Set-Content -Path $EnvFile", step17)
        self.assertIn("if (-not (Start-JarvisProcess))", step17)
        persist_offset = step17.index("Set-Content -Path $EnvFile")
        first_restart_offset = step17.index("if (-not (Start-JarvisProcess))")
        self.assertLess(
            persist_offset,
            first_restart_offset,
            "a gravacao em .env deve ocorrer ANTES da primeira chamada "
            "que efetivamente reinicia o Jarvis (o restart controlado "
            "pos-migration), nunca depois -- senao o restart usaria a "
            "URL antiga/vazia do ambiente do processo em vez da nova.",
        )

    def test_step_order_10_12_15_16_17_is_strictly_increasing(self):
        sequence = [10, 12, 15, 16, 17]
        step_offsets = [self.offsets[n] for n in sequence]
        self.assertEqual(
            step_offsets,
            sorted(step_offsets),
            "a ordem estrutural STEP 10 -> 12 -> 15 -> 16 -> 17 deve "
            "permanecer estritamente crescente no arquivo (schema -> "
            "dry-run -> import real -> idempotencia -> "
            "persistencia+restart) -- esta suite nao deve alterar essa "
            "ordem, apenas o QUE acontece dentro do STEP 9 e do STEP "
            "17.",
        )

    def test_reused_existing_url_branch_does_not_write_env_file(self):
        step9 = _slice_step(self.text, self.offsets, 9, 10)
        reused_marker = "existing_env_reused"
        self.assertIn(reused_marker, step9)
        reused_offset = step9.index(reused_marker)
        preamble = step9[:reused_offset]
        self.assertNotIn(
            "Set-Content -Path $EnvFile",
            preamble,
            "o ramo que reaproveita uma JARVIS_DATABASE_URL ja valida em "
            ".env nao deve, em nenhuma circunstancia, reescrever o "
            "arquivo.",
        )


if __name__ == "__main__":
    unittest.main()
