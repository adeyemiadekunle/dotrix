def test_engine_imports() -> None:
    import dotrix_engine

    assert callable(dotrix_engine.build_agent)
