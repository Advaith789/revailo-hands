from takeoff.config import loader, toml_lite


def test_toml_lite_parses_sections_and_scalars():
    data = toml_lite.loads('[a]\nx = 1\ny = 2.5\nz = "s" # c\nb = true\n[b]\nq = false\n')
    assert data == {"a": {"x": 1, "y": 2.5, "z": "s", "b": True}, "b": {"q": False}}


def test_defaults_are_used_when_no_file(tmp_path):
    s = loader.load(path=tmp_path / "missing.toml", environ={})
    assert s.retry.max_attempts == 4
    assert s.source == "defaults"


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text("[retry]\nmax_attempts = 9\n")
    s = loader.load(path=p, environ={})
    assert s.retry.max_attempts == 9
    assert s.retry.backoff_base_s == 0.01


def test_env_overrides_file(tmp_path):
    p = tmp_path / "settings.toml"
    p.write_text("[retry]\nmax_attempts = 9\n")
    s = loader.load(path=p, environ={"TAKEOFF_RETRY__MAX_ATTEMPTS": "2"})
    assert s.retry.max_attempts == 2


def test_unset_flag_defaults_off(tmp_path):
    s = loader.load(path=tmp_path / "missing.toml", environ={})
    assert s.section("flags").get("nope", False) is False
