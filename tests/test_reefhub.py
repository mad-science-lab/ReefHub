from reefhub.model import parse_status
from reefhub.mqtt import FeedCommand, OutletCommand, parse_command

STATUS = {
    "system": {"serial": "AC6:12345", "hostname": "apex", "software": "5.15L", "hardware": "1.0"},
    "inputs": [
        {"did": "base_Temp", "type": "Temp", "name": "Tank Temp", "value": 78.1},
        {"did": "base_pH", "type": "pH", "name": "pH", "value": "8.12"},
        {"did": "sw1", "type": "digital", "name": "Float", "value": 1},
    ],
    "outputs": [
        {"did": "2_1", "name": "Heater", "type": "outlet", "status": ["AON", "", "OK", ""]},
        {"did": "2_2", "name": "Skimmer", "type": "outlet", "status": ["OFF", "", "OK", ""]},
        {"did": "2_3", "name": "Return", "type": "outlet", "status": ["ON", "", "OK", ""]},
        {"did": "2_4", "name": "Light", "type": "outlet", "status": ["TBL", "", "OK", ""]},
    ],
    "feed": {"name": 2, "active": 300},
}


def test_outlet_modes():
    snap = parse_status(STATUS)
    modes = {o.did: (o.mode, o.energized) for o in snap.outlets}
    assert modes == {
        "2_1": ("AUTO", True),
        "2_2": ("OFF", False),
        "2_3": ("ON", True),
        "2_4": ("AUTO", True),
    }


def test_percent_only_when_reported():
    status = {**STATUS, "outputs": [
        {"did": "2_1", "name": "Return", "type": "outlet", "status": ["AON", "90", "OK", ""]},
        {"did": "2_2", "name": "Skim", "type": "outlet", "status": ["AON", "", "OK", ""]},
        {"did": "2_3", "name": "Pump", "type": "outlet", "status": ["OFF", "0", "OK", ""]},
    ]}
    pct = {o.did: o.percent for o in parse_status(status).outlets}
    assert pct == {"2_1": 90, "2_2": None, "2_3": 0}


def test_pump_mode_from_mxm_pumps_only():
    status = {**STATUS, "outputs": [
        {"did": "3_1", "name": "Vortech", "type": "MXMPump|Ecotech|Vortech",
         "status": ["TBL", "", "Off", "OK"]},
        {"did": "3_5", "name": "Nero", "type": "MXMPump|AI|Nero5", "status": ["TBL", "", "", "OK"]},
        {"did": "3_2", "name": "Radion", "type": "MXMLight|Ecotech|15G6P",
         "status": ["TBL", "", "Off", "OK"]},
        {"did": "2_1", "name": "Heater", "type": "outlet", "status": ["AON", "", "OK", ""]},
    ]}
    modes = {o.did: o.pump_mode for o in parse_status(status).outlets}
    assert modes == {"3_1": "Off", "3_5": None, "3_2": None, "2_1": None}


def test_raw_state_kept():
    snap = parse_status(STATUS)
    assert {o.did: o.raw_state for o in snap.outlets} == {
        "2_1": "AON", "2_2": "OFF", "2_3": "ON", "2_4": "TBL",
    }


def test_probes_and_feed():
    snap = parse_status(STATUS)
    values = {p.did: p.value for p in snap.probes}
    assert values == {"base_Temp": 78.1, "base_pH": 8.12, "sw1": True}
    assert snap.feed.mode == "B"
    assert snap.feed.seconds_remaining == 300


def test_garbage_feed_is_idle():
    # What the controller reports after cancelling an idle feed.
    snap = parse_status({**STATUS, "feed": {"name": 256, "active": 61438}})
    assert snap.feed.mode == "OFF"
    assert snap.feed.seconds_remaining == 0
    assert snap.feed.raw_name == 256


def test_outlet_commands():
    assert parse_command("reefhub", "reefhub/outlet/2_1/set", b"auto") == OutletCommand("2_1", "AUTO")
    assert parse_command("reefhub", "reefhub/outlet/2_1/set", b'"Off"') == OutletCommand("2_1", "OFF")
    assert parse_command("reefhub", "reefhub/outlet/2_1/set", b"toast") is None


def test_feed_commands():
    assert parse_command("reefhub", "reefhub/feed/set", b"A") == FeedCommand(1)
    assert parse_command("reefhub", "reefhub/feed/set", b"d") == FeedCommand(4)
    assert parse_command("reefhub", "reefhub/feed/set", b"3") == FeedCommand(3)
    assert parse_command("reefhub", "reefhub/feed/set", b"CANCEL") == FeedCommand(0)
    assert parse_command("reefhub", "reefhub/feed/set", b"E") is None




def test_grouping_by_module():
    from reefhub.model import group_default_name, group_key

    status = {
        **STATUS,
        "system": {**STATUS["system"], "type": "AC6L"},
        "modules": [{"abaddr": 2, "hwtype": "eb832"}, {"abaddr": 3, "hwtype": "fmm"}],
        "outputs": [
            {"did": "2_1", "name": "A", "type": "outlet", "module_abaddr": 2, "status": ["AON"]},
            {"did": "Cntl_A4", "name": "V", "type": "virtual", "status": ["OFF"]},
        ],
    }
    snap = parse_status(status)
    assert group_key("2_P0") == "m2"
    assert group_key("base_Temp") == "base"
    assert group_key("Cntl_A4") == "x_cntl"
    assert group_key("2_1", snap.outlets[0].module) == "m2"
    assert group_default_name("m2", snap) == "ReefHub EB832 #2"
    assert group_default_name("m9", snap) == "ReefHub Module #9"
    assert group_default_name("base", snap) == "ReefHub Apex base (AC6L)"
