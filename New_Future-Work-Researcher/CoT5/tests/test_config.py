import asyncio
from pathlib import Path

from cot5.config import SUBMODULE_DIR, load_config, submodule_cwd


def test_submodule_cwd_restores_after_overlapping_async_calls(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    async def run():
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()
        first_exited = asyncio.Event()

        async def first():
            with submodule_cwd():
                first_entered.set()
                await second_entered.wait()
                assert Path.cwd() == SUBMODULE_DIR
            first_exited.set()

        async def second():
            await first_entered.wait()
            with submodule_cwd():
                second_entered.set()
                await first_exited.wait()
                assert Path.cwd() == SUBMODULE_DIR

        await asyncio.gather(first(), second())

    asyncio.run(run())
    assert Path.cwd() == tmp_path


def test_submodule_cwd_restores_after_exception(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    try:
        with submodule_cwd():
            raise RuntimeError("failure")
    except RuntimeError:
        pass
    assert Path.cwd() == tmp_path


def test_load_config_writes_loader_status_to_stderr(capsys, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text("{}\n", encoding="utf-8")
    load_config(config_path)
    output = capsys.readouterr()
    assert output.out == ""
    assert "Loaded environment variables" in output.err
