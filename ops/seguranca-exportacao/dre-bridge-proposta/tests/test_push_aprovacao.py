# -*- coding: utf-8 -*-
"""publicar_no_git: push so com DRE_BRIDGE_ALLOW_PUSH=1 (git e rede mockados).

    python -m unittest discover -s tests -v
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPT = Path(os.environ.get(
    "DRE_BRIDGE_SCRIPT", Path(__file__).resolve().parents[1] / "baixar_dres_local.py"))


def carregar():
    spec = importlib.util.spec_from_file_location("baixar_dres_local", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeGit:
    """Responde aos comandos git sem executar nada; guarda o que foi pedido."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, cmd, **kw):
        self.chamadas.append(cmd[1:])
        out = ""
        if cmd[1:3] == ["diff", "--cached"]:
            out = "DRE Julho.xlsx\n"
        elif cmd[1] == "rev-list":
            out = "3\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    def pediu(self, sub):
        return any(c and c[0] == sub for c in self.chamadas)


class PushSoComAprovacao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.mod = carregar()
        self.mod.DEST_TRABALHO = base / "trabalho"
        (self.mod.DEST_TRABALHO / ".git").mkdir(parents=True)
        self.arquivo = self.mod.DEST_TRABALHO / "DRE Julho.xlsx"
        self.arquivo.write_bytes(b"x")
        self.mod.LOG_GIT = base / "git_publicacao.log"
        self.git = FakeGit()

    def tearDown(self):
        self.tmp.cleanup()

    def rodar(self, ambiente, urlopen=None):
        urlopen = urlopen or mock.MagicMock(side_effect=AssertionError("rede nao deveria ser usada"))
        with mock.patch.dict(os.environ, ambiente, clear=False), \
                mock.patch("subprocess.run", self.git), \
                mock.patch("urllib.request.urlopen", urlopen):
            self.mod.publicar_no_git([self.arquivo])
        return urlopen

    def log(self):
        return self.mod.LOG_GIT.read_text(encoding="utf-8")

    def test_padrao_commita_local_e_nao_faz_push_nem_rede(self):
        os.environ.pop("DRE_BRIDGE_ALLOW_PUSH", None)
        urlopen = self.rodar({})
        self.assertTrue(self.git.pediu("commit"))
        self.assertFalse(self.git.pediu("push"))
        urlopen.assert_not_called()
        self.assertIn("PUSH PENDENTE DE APROVACAO", self.log())
        self.assertIn("Commits aguardando push: 3", self.log())

    def test_valores_diferentes_de_1_nao_liberam_push(self):
        for valor in ("", "0", "true", "sim", "yes"):
            self.git = FakeGit()
            self.rodar({"DRE_BRIDGE_ALLOW_PUSH": valor})
            self.assertFalse(self.git.pediu("push"), valor)

    def test_flag_1_com_repo_privado_faz_push(self):
        privado = mock.MagicMock(side_effect=urllib.error.HTTPError(
            "u", 404, "Not Found", None, None))
        self.rodar({"DRE_BRIDGE_ALLOW_PUSH": "1"}, privado)
        self.assertTrue(self.git.pediu("push"))
        self.assertIn("Publicado no GitHub", self.log())

    def test_flag_1_com_repo_publico_nao_faz_push(self):
        resp = mock.MagicMock(status=200)
        resp.__enter__.return_value = resp
        self.rodar({"DRE_BRIDGE_ALLOW_PUSH": "1"}, mock.MagicMock(return_value=resp))
        self.assertTrue(self.git.pediu("commit"))
        self.assertFalse(self.git.pediu("push"))
        self.assertIn("PUBLICO", self.log())

    def test_flag_1_sem_conseguir_checar_visibilidade_nao_faz_push(self):
        self.rodar({"DRE_BRIDGE_ALLOW_PUSH": "1"}, mock.MagicMock(side_effect=OSError("offline")))
        self.assertFalse(self.git.pediu("push"))


if __name__ == "__main__":
    unittest.main()
