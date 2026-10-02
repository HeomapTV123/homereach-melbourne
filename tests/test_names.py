from homereach.utils.names import normalise_name


def test_normalise_name_is_conservative() -> None:
    assert normalise_name("  Boroondara (C) ") == "BOROONDARA C"
    assert normalise_name("Banyule & Nillumbik") == "BANYULE AND NILLUMBIK"
    assert normalise_name(None) is None
