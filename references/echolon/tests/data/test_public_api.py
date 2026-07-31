"""echolon.data public surface is discoverable and fully importable."""


def test_all_exports_importable():
    """Every name in echolon.data.__all__ must be importable as an attribute."""
    import echolon.data as d

    for name in d.__all__:
        assert hasattr(d, name), f"missing export: {name}"
