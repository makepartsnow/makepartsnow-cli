from __future__ import annotations

import os
import stat
import sys

import pytest

from makepartsnow import __version__, cli, state

from .conftest import load_fixture, run, structured

STEP = b"ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('C:\\\\Users\\\\pat\\\\tmp\\\\Bracket.step','2026-10-18T00:00:00',('Pat Example'),('Acme Corp'),'x','y','');\nFILE_SCHEMA(('AP214'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


@pytest.fixture
def parts(tmp_path):
    step = tmp_path / "Bracket.step"
    step.write_bytes(STEP)
    stl = tmp_path / "Cover.stl"
    stl.write_bytes(b"solid x\nendsolid x\n")
    return step, stl


def quote_transport(transport, *quote_answers):
    return transport.queue("quote_parts", *(quote_answers or ("quote_parts_ready",)))


def test_options_lists_materials_and_json_has_the_version(transport):
    r = run(transport, "options")
    assert r.code == 0 and "pa12" in r.out and "fdm_pla" in r.out and "CAD10" in r.out
    j = run(transport, "options", "--json").json
    assert j["cli_version"] == __version__ and j["materials"][0]["id"] == "pa12"


def test_every_request_is_tagged_and_named(transport):
    run(transport, "options")
    posts = [c for c in transport.calls if c["method"] == "POST"]
    assert posts and all(c["url"] == "https://makepartsnow.com/mcp/cad?client=cli" for c in posts)
    assert {c["headers"]["User-Agent"] for c in posts} == {f"MakePartsNow-CLI/{__version__}"}


def test_quote_uploads_scrubbed_copies_and_prices_each_line(transport, parts, config):
    step, stl = parts
    r = run(quote_transport(transport), "quote", f"{step}:10", str(stl), "--zip", "89101", "--qty", "3", "--material", "pa12",
            "--finish", "black", "--units", "mm", "--yes")
    assert r.code == 0, r.err
    links = transport.tool_calls("create_upload_links")[0]["arguments"]
    assert links["count"] == 2 and links["file_names"] == ["Bracket.step", "Cover.stl"]
    sent_step, sent_stl = transport.put_bodies
    assert b"Pat Example" not in sent_step and b"Acme Corp" not in sent_step and b"Users" not in sent_step
    assert step.read_bytes() == STEP  # the original is untouched
    assert sent_stl == stl.read_bytes()
    items = transport.tool_calls("quote_parts")[0]["arguments"]
    assert items["ship_to_zip"] == "89101"
    assert [(i["quantity"], i["material"], i["finish"], i.get("units")) for i in items["items"]] == [(10, "pa12", "black", None), (3, "pa12", "black", "mm")]
    assert "Total $40.20 before tax" in r.out and "https://makepartsnow.com/quotes/share/abc" in r.out
    assert state.last_zip() == "89101"
    saved = state.uploads()
    assert [(u["part_id"], u["delete_token"]) for u in saved] == [("part_a", "dt_a"), ("part_b", "dt_b")]
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(config / "uploads.json").st_mode) == 0o600


def test_first_run_off_a_terminal_needs_yes_and_sends_no_file(transport, parts):
    r = run(quote_transport(transport), "quote", str(parts[0]), "--zip", "89101")
    assert r.code == 1 and "--yes" in r.err
    assert not transport.tool_calls("create_upload_links") and not transport.put_bodies


def test_first_run_on_a_terminal_asks_once(transport, parts):
    no = run(quote_transport(transport), "quote", str(parts[0]), "--zip", "89101", answers=("n",), interactive=True)
    assert no.code == 1 and "what this sends" in no.err and not transport.put_bodies
    yes = run(transport, "quote", str(parts[0]), "--zip", "89101", answers=("y",), interactive=True)
    assert yes.code == 0 and state.has_consent()
    again = run(transport, "quote", str(parts[0]), "--zip", "89101", interactive=False)
    assert again.code == 0  # consent is remembered


def test_mpn_accept_counts_as_consent(transport, parts, monkeypatch):
    monkeypatch.setenv("MPN_ACCEPT", "1")
    assert run(quote_transport(transport), "quote", str(parts[0]), "--zip", "89101").code == 0


def test_zip_is_required_then_remembered(transport, parts):
    assert run(quote_transport(transport), "quote", str(parts[0]), "--yes").code == 1
    assert run(transport, "quote", str(parts[0]), "--zip", "10001", "--yes").code == 0
    assert run(transport, "quote", str(parts[0]), "--yes").code == 0
    assert transport.tool_calls("quote_parts")[-1]["arguments"]["ship_to_zip"] == "10001"


def test_bad_material_or_finish_lists_the_choices(transport, parts):
    r = run(transport, "quote", str(parts[0]), "--zip", "89101", "--material", "unobtainium", "--yes")
    assert r.code == 1 and "pa12" in r.err and "fdm_pla" in r.err
    r = run(transport, "quote", str(parts[0]), "--zip", "89101", "--finish", "plaid", "--yes")
    assert r.code == 1 and "gray, black" in r.err


def test_files_are_checked_before_anything_is_sent(transport, tmp_path):
    missing = run(transport, "quote", str(tmp_path / "nope.step"), "--zip", "89101", "--yes")
    assert missing.code == 1 and "No such file" in missing.err
    obj = tmp_path / "part.obj"
    obj.write_text("o x")
    wrong = run(transport, "quote", str(obj), "--zip", "89101", "--yes")
    assert wrong.code == 1 and "step, stl, stp" in wrong.err
    assert not transport.put_bodies


def test_needs_input_exits_2_and_shows_the_reason(transport, parts):
    r = run(quote_transport(transport, "quote_parts_needs_input"), "quote", str(parts[0]), str(parts[1]), "--zip", "89101", "--yes")
    assert r.code == 2 and "PROCESS_NOT_AVAILABLE" in r.out


def test_processing_is_polled_until_ready(transport, parts, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    r = run(quote_transport(transport, "quote_parts_processing", "quote_parts_ready"), "quote", str(parts[0]), "--zip", "89101", "--yes")
    assert r.code == 0 and len(transport.tool_calls("quote_parts")) == 2


def test_checkout_open_opens_only_makepartsnow(transport, parts, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    r = run(quote_transport(transport).queue("create_checkout_link", "create_checkout_link"), "quote", str(parts[0]), "--zip", "89101", "--open", "--yes", "--json")
    assert r.code == 0 and opened == ["https://makepartsnow.com/pay/ptok123"]
    assert r.json["checkout"]["opened"] is True and r.json["checkout"]["checkout_url"].endswith("ptok123")
    evil = structured({"status": "ready", "checkout_url": "https://evil.example/pay/x", "total_price": 1.0, "link_valid_until": "x",
                       "quote_url": "", "promo": None, "error": None})
    opened.clear()
    transport.queue("create_checkout_link", evil)
    transport.answers["create_checkout_link"] = [evil]
    r = run(transport, "checkout", "quote_q1", "--open")
    assert opened == []


def test_delete_after_quoting(transport, parts):
    r = run(quote_transport(transport).queue("delete_parts", "delete_parts"), "quote", str(parts[0]), "--zip", "89101", "--delete", "--yes")
    assert r.code == 0 and "Deleted 1 file" in r.out
    sent = transport.tool_calls("delete_parts")[0]["arguments"]["parts"]
    assert sent == [{"part_id": "part_a", "delete_token": "dt_a"}, {"part_id": "part_b", "delete_token": "dt_b"}]
    assert [u["part_id"] for u in state.uploads()] == ["part_b"]  # on an order: kept, and said so
    assert "on an order" in r.out


def test_delete_all_later_and_list(transport, parts):
    run(quote_transport(transport), "quote", str(parts[0]), "--zip", "89101", "--yes")
    listed = run(transport, "delete", "--list", "--json").json
    assert [u["part_id"] for u in listed["uploads"]] == ["part_a", "part_b"] and "delete_token" not in listed["uploads"][0]
    transport.queue("delete_parts", structured({"deleted": ["part_a", "part_b"], "errors": []}))
    r = run(transport, "delete", "--all")
    assert r.code == 0 and state.uploads() == []
    assert run(transport, "delete", "part_zzz").code == 1


def test_requote_keeps_the_files(transport):
    transport.queue("get_quote", "quote_parts_ready").queue("update_quote", "update_quote")
    r = run(transport, "requote", "quote_q1", "--qty", "5", "--finish", "black", "--zip", "89101")
    assert r.code in (0, 2)
    args = transport.tool_calls("update_quote")[0]["arguments"]
    assert args["quote_id"] == "quote_q1" and all(i["quantity"] == 5 and i["finish"] == "black" and "part_id" in i for i in args["items"])


def test_paused_service_exits_3(transport, parts):
    paused = load_fixture("get_options_materials")
    paused["result"]["structuredContent"]["enabled"] = False
    transport.answers["get_options"] = [paused]
    r = run(transport, "quote", str(parts[0]), "--zip", "89101", "--yes")
    assert r.code == 3 and "paused" in r.err and not transport.put_bodies


def test_too_old_exits_3(transport):
    old = load_fixture("get_options_materials")
    old["result"]["structuredContent"]["min_client_version"] = "9.0.0"
    transport.answers["get_options"] = [old]
    r = run(transport, "options")
    assert r.code == 3 and "pip install -U makepartsnow" in r.err


@pytest.mark.parametrize("arg,expected", [
    ("bracket.step:10", ("bracket.step", 10)),
    ("bracket.step", ("bracket.step", None)),
    ("C:\\cad\\bracket.step", ("C:\\cad\\bracket.step", None)),
    ("C:\\cad\\bracket.step:4", ("C:\\cad\\bracket.step", 4)),
    ("odd:name.stl", ("odd:name.stl", None)),
])
def test_file_quantity_syntax(arg, expected):
    assert cli.split_file_arg(arg) == expected


def test_base_url_override(transport, monkeypatch):
    monkeypatch.setenv("MPN_BASE_URL", "http://evil.example")
    assert run(transport, "options").code == 1
    monkeypatch.setenv("MPN_BASE_URL", "http://127.0.0.1:8095/")
    r = run(transport, "options")
    assert r.code == 0 and "TEST" in r.err
    assert transport.calls[-1]["url"] == "http://127.0.0.1:8095/mcp/cad?client=cli"


def test_unit_price_keeps_a_third_decimal():
    assert cli.unit_money(3.655) == "$3.655" and cli.unit_money(2.96) == "$2.96" and cli.unit_money(None) == "-"
