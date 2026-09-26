def test_engine_imports() -> None:
    import pmagent_engine

    assert callable(pmagent_engine.build_agent)
