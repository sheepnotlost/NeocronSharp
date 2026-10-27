from ntc.names import Names


def make(tmp_path):
    return Names(tmp_path / "k.json")


def test_new_name_flagged_then_known(tmp_path):
    n = make(tmp_path)
    assert n.normalize("Core Part Of HOLY DEFLECTION") == ("Core Part Of HOLY DEFLECTION", ["NEW_NAME"])
    assert n.normalize("Core Part Of HOLY DEFLECTION") == ("Core Part Of HOLY DEFLECTION", [])


def test_ocr_noise_is_corrected(tmp_path):
    n = make(tmp_path)
    n.normalize("Core Part Of HOLY DEFLECTION")
    assert n.normalize("Core Part Of HOLY DEFLECT1ON")[0] == "Core Part Of HOLY DEFLECTION"


def test_part_type_misread_is_corrected(tmp_path):
    n = make(tmp_path)
    assert n.normalize("Additional Technoloav Part Of HOLY ABSORPTION")[0] == "Additional Technology Part Of HOLY ABSORPTION"
    assert n.normalize("Technoloav Part Of HOLY PROTECTION")[0] == "Technology Part Of HOLY PROTECTION"


def test_different_part_types_never_merge(tmp_path):
    """Regression: 'Frame ...' and 'Core ...' with the same suffix scored 0.91 and were merged."""
    n = make(tmp_path)
    n.normalize("Core Part Of HOLY DEFLECTION")
    name, flags = n.normalize("Frame Part Of HOLY DEFLECTION")
    assert name == "Frame Part Of HOLY DEFLECTION" and flags == ["NEW_NAME"]


def test_unread_name(tmp_path):
    assert make(tmp_path).normalize(None) == ("?", ["NAME_UNREAD"])


def test_teach_alias_persists(tmp_path):
    n = make(tmp_path)
    n.teach("Garbled Text", "Hull Part Of HOLY PROTECTION")
    assert make(tmp_path).normalize("garbled text") == ("Hull Part Of HOLY PROTECTION", [])


def test_items_differing_in_a_digit_never_merge(tmp_path):
    """Regression risk: dog tags differ only in their numbers ('51/ 56' vs '51/ 58'); roman numerals differ in length."""
    n = make(tmp_path)
    n.normalize("Dog Tag Of Bad Larry, ProtoPharm, 51/ 56")
    assert n.normalize("Dog Tag Of Bad Larry, ProtoPharm, 51/ 58")[1] == ["NEW_NAME"]
    n.normalize("Ultima Enhancement II")
    assert n.normalize("Ultima Enhancement III")[1] == ["NEW_NAME"]


def test_ocr_lookalikes_do_merge(tmp_path):
    n = make(tmp_path)
    n.normalize("Tsunami Syndicate")
    assert n.normalize("Tsunami Svndicate") == ("Tsunami Syndicate", [])
    n.normalize("Gatling Cannon Ammo - Phosphor")
    assert n.normalize("Gatling Cannon Ammo - Phosph0r") == ("Gatling Cannon Ammo - Phosphor", [])


def test_is_tech(tmp_path):
    n = make(tmp_path)
    for tech in ("Core Part Of HOLY DEFLECTION", "Additional Technology Part Of ZSUSUN", "Frame Part Of RAVAGER",
                 "Technology Part Of CREED", "Component Part Of PEACEMAKER", "Hull Part Of LIBERATOR"):
        assert n.is_tech(tech), tech
    for other in ("Dog Tag Of Bad Larry, ProtoPharm, 51/ 56", "Gatling Cannon Ammo - Phosphor", "WarBot Remains",
                  "Rifle-Ultima-Enhancement", "Weapon Part Of Something"):
        assert not n.is_tech(other), other


def test_techs_only_skips_everything_else_and_does_not_remember_it(tmp_path):
    n = make(tmp_path)
    assert n.normalize("WarBot Remains", techs_only=True) == ("WarBot Remains", ["SKIP"])
    assert n.data["names"] == []                                   # not added to known_items
    assert n.normalize("Core Part Of HOLY DEFLECTION", techs_only=True)[1] == ["NEW_NAME"]
    assert n.normalize(None, techs_only=True) == ("?", ["NAME_UNREAD"])    # unreadable: keep for review, might be a tech


def test_techs_only_applies_to_taught_names_too(tmp_path):
    n = make(tmp_path)
    n.teach("Garbled", "WarBot Remains")
    assert n.normalize("garbled", techs_only=True)[1] == ["SKIP"] and n.normalize("garbled")[1] == []
