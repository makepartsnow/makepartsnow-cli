"""``mpn``: instant Make Parts Now quotes for CAD files, from the terminal or a script.

Built on the vendored Make Parts Now CAD core (``makepartsnow.core``): the same client the Fusion add-in and the
FreeCAD workbench use, on ``https://makepartsnow.com/mcp/cad?client=cli``. No account and no key. The CLI never
pays: ``--checkout`` makes a link you open to pay on makepartsnow.com.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import webbrowser
from typing import Any, Callable, Optional, Sequence, TextIO

from . import __version__, state
from .core import export
from .core.client import (
    CadClient,
    CadError,
    Checkout,
    Options,
    QuoteItem,
    QuoteView,
    is_older,
    requote_items,
    to_jsonable,
)
from .core.settings import is_allowed_base_url
from .core.text import is_allowed_link

DEFAULT_BASE_URL = "https://makepartsnow.com"
CLIENT_NAME = "cli"
PRODUCT = "CLI"
MAX_WAIT_S = 180.0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NEEDS_INPUT = 2
EXIT_UNAVAILABLE = 3

CONSENT_TEXT = """Before your first quote: what this sends, and where.

- To makepartsnow.com only: each file you name (a STEP file is sent as a copy with the author, organization and
  path blanked in its header), the quantity, material and finish you choose, and the ZIP code the parts ship to.
- Nothing else: no other files, no account, no usage counts.
- Uploaded files are stored encrypted and deleted automatically under the privacy policy
  (https://makepartsnow.com/legal/privacy); `mpn delete --all` deletes them sooner. Files on an order stay with it.
- You order and pay on makepartsnow.com through Stripe. This tool never pays.
"""


class UsageError(Exception):
    """A mistake in the command line: exit 1 with the message, no traceback."""


# ------------------------------------------------------------------ setup


def base_url() -> str:
    override = os.environ.get("MPN_BASE_URL", "").strip()
    if not override:
        return DEFAULT_BASE_URL
    if not is_allowed_base_url(override):
        raise UsageError("MPN_BASE_URL must be https, or http to localhost.")
    return override.rstrip("/")


def make_client(transport: Any = None) -> CadClient:
    return CadClient(base_url(), __version__, client_name=CLIENT_NAME, product=PRODUCT, transport=transport)


def checked_options(client: CadClient) -> Options:
    options = client.get_options()
    if not options.enabled:
        raise CadError("SERVICE_PAUSED", "Instant quotes are paused right now. Try again later, or quote on makepartsnow.com.")
    if is_older(__version__, options.min_client_version):
        raise CadError("CLIENT_TOO_OLD", f"This version ({__version__}) is too old. Update it: pip install -U makepartsnow")
    return options


def split_file_arg(arg: str) -> tuple[str, Optional[int]]:
    """``bracket.step:10`` gives a file and its quantity; a Windows drive letter (``C:\\x.step``) is not a quantity."""
    head, sep, tail = arg.rpartition(":")
    if sep and head and tail.isdigit():
        return head, int(tail)
    return arg, None


def file_kind(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


# ------------------------------------------------------------------ output


class Out:
    def __init__(self, as_json: bool, stdout: TextIO, stderr: TextIO) -> None:
        self.as_json, self.stdout, self.stderr = as_json, stdout, stderr

    def line(self, text: str = "") -> None:
        if not self.as_json:
            print(text, file=self.stdout)

    def note(self, text: str) -> None:
        print(text, file=self.stderr)

    def data(self, obj: Any) -> None:
        if self.as_json:
            payload = to_jsonable(obj) if not isinstance(obj, dict) else obj
            if isinstance(payload, dict):
                payload = {**payload, "cli_version": __version__}
            print(json.dumps(payload, indent=2), file=self.stdout)


def money(value: Optional[float]) -> str:
    return "-" if value is None else f"${value:,.2f}"


def unit_money(value: Optional[float]) -> str:
    """A unit price keeps a third decimal when it has one ($3.655), so quantity x unit price = line total reads right."""
    if value is None:
        return "-"
    return f"${value:,.2f}" if abs(round(value, 2) - value) < 1e-9 else f"${value:,.3f}"


def dims(values: Optional[Sequence[float]]) -> str:
    return " x ".join(f"{v:g}" for v in values) + " mm" if values else "-"


def show_quote(out: Out, view: QuoteView) -> None:
    out.line(f"Quote {view.quote_id or '(not ready)'}: {view.status}")
    for part in view.parts:
        out.line(f"  {part.file_name or part.part_id}  {dims(part.dimensions_mm)}  {part.material_name}, {part.finish}"
                 f"  {part.quantity} x {unit_money(part.unit_price)} = {money(part.line_total)}")
        for warning in part.warnings:
            out.line(f"    ! {warning}")
        if part.error:
            out.line(f"    x {part.error.code}: {part.error.message}")
            if part.error.allowed_values:
                out.line(f"      allowed: {', '.join(part.error.allowed_values)}")
    totals = view.totals
    if totals:
        out.line(f"  Parts {money(totals.parts_subtotal)}"
                 + (f"  discount -{money(totals.discount)}" if totals.discount else "")
                 + f"  shipping {'free' if totals.free_shipping else money(totals.shipping)}"
                 + (" (estimated)" if totals.shipping_estimated else ""))
        out.line(f"  Total {money(totals.total_price)} before tax, Standard speed")
    if view.estimated_ship_date:
        out.line(f"  Ships by {view.estimated_ship_date}, arrives by {view.estimated_arrival_date}")
    if view.price_valid_until:
        out.line(f"  Price held until {view.price_valid_until[:10]}")
    if view.promo and view.promo.note:
        out.line(f"  {view.promo.note}")
    if view.quote_url:
        out.line(f"  {view.quote_url}")
    if view.status != "ready" and view.next_step:
        out.line(f"  Next: {view.next_step}")


def show_checkout(out: Out, checkout: Checkout, opened: bool) -> None:
    if checkout.status != "ready" or not checkout.checkout_url:
        detail = f" ({checkout.error.code}: {checkout.error.message})" if checkout.error else ""
        out.line(f"Checkout isn't ready: {checkout.status}{detail}")
        return
    out.line(f"Checkout: {checkout.checkout_url}")
    out.line(f"  Total {money(checkout.total_price)} before tax; pay on makepartsnow.com"
             + (" (opened in your browser)" if opened else ""))
    if checkout.promo and checkout.promo.note:
        out.line(f"  {checkout.promo.note}")


def quote_exit(view: QuoteView) -> int:
    return EXIT_OK if view.is_ready else EXIT_NEEDS_INPUT


# ------------------------------------------------------------------ commands


def ensure_consent(args: argparse.Namespace, out: Out, ask: Callable[[str], str], interactive: bool) -> None:
    if state.has_consent():
        return
    if args.yes or os.environ.get("MPN_ACCEPT") == "1":
        state.record_consent()
        return
    if not interactive:
        raise UsageError("First run: read what is sent (run `mpn quote` in a terminal), or pass --yes (or set MPN_ACCEPT=1).")
    out.note(CONSENT_TEXT)
    if ask("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
        raise UsageError("Nothing was sent.")
    state.record_consent()


def pick_material(options: Options, material: Optional[str], finish: Optional[str]) -> tuple[str, str]:
    ids = [m.id for m in options.materials] or [options.material_id]
    material_id = material or ids[0]
    if material_id not in ids:
        raise UsageError(f"--material must be one of: {', '.join(ids)} (see `mpn options`).")
    chosen = options.material(material_id)
    finishes = [f.id for f in chosen.finishes]
    finish_id = finish or (finishes[0] if finishes else "")
    if finishes and finish_id not in finishes:
        raise UsageError(f"--finish for {material_id} must be one of: {', '.join(finishes)}.")
    return material_id, finish_id


def cmd_options(args: argparse.Namespace, client: CadClient, out: Out) -> int:
    options = checked_options(client)
    out.data(options)
    out.line(f"Materials (Standard speed; up to {options.max_parts} files, {options.max_quantity} each, "
             f"{options.max_file_mb:g} MB; {', '.join(options.file_formats)}):")
    for m in options.materials:
        out.line(f"  {m.id:<14} {m.name} ({m.process.upper()}, up to {dims(m.build_volume_mm)})")
        out.line(f"  {'':<14} finishes: {', '.join(f.id for f in m.finishes)}")
    if options.free_shipping_threshold:
        out.line(f"Free shipping from {money(options.free_shipping_threshold)}.")
    if options.promo and options.promo.note:
        out.line(options.promo.note)
    return EXIT_OK


def cmd_quote(args: argparse.Namespace, client: CadClient, out: Out, ask: Callable[[str], str], interactive: bool) -> int:
    files = [split_file_arg(a) for a in args.files]
    zip_code = (args.zip or state.last_zip() or "").strip()
    if not zip_code:
        raise UsageError("Pass --zip with the US ZIP code the parts ship to.")
    if args.qty is not None and args.qty < 1:
        raise UsageError("--qty must be 1 or more.")
    options = checked_options(client)
    if len(files) > options.max_parts:
        raise UsageError(f"Quote up to {options.max_parts} files at a time.")
    formats = {f.lower() for f in options.file_formats}
    for path, qty in files:
        if not os.path.isfile(path):
            raise UsageError(f"No such file: {path}")
        if file_kind(path) not in formats:
            raise UsageError(f"{path}: the formats quoted here are {', '.join(sorted(formats))}.")
        if os.path.getsize(path) > options.max_file_mb * 1024 * 1024:
            raise UsageError(f"{path} is larger than {options.max_file_mb:g} MB.")
        if qty is not None and not 1 <= qty <= options.max_quantity:
            raise UsageError(f"{path}: the quantity must be 1 to {options.max_quantity}.")
    material_id, finish_id = pick_material(options, args.material, args.finish)
    ensure_consent(args, out, ask, interactive)

    temp_dir = export.make_temp_dir()
    try:
        names: set[str] = set()
        uploads: list[tuple[str, str, int, Optional[str]]] = []  # (path to send, file name, quantity, units)
        for path, qty in files:
            kind = file_kind(path)
            stem = os.path.splitext(os.path.basename(path))[0]
            name = export.safe_file_name(stem, kind, names)
            send = path
            if kind in ("step", "stp"):
                send = os.path.join(temp_dir, name)
                shutil.copyfile(path, send)
                export.scrub_step_header(send, name)  # on the copy: the original is never changed
            units = args.units if kind == "stl" else None
            uploads.append((send, name, qty or args.qty or 1, units))
        out.note(f"Uploading {len(uploads)} file(s) to makepartsnow.com...")
        links = client.create_upload_links(len(uploads), [u[1] for u in uploads])
        items = []
        for (send, name, qty, units), link in zip(uploads, links):
            with open(send, "rb") as fh:
                client.put_file(link, fh.read(), name)
            items.append(QuoteItem(quantity=qty, finish=finish_id, upload_id=link.upload_id, units=units, material=material_id))
    finally:
        export.cleanup(temp_dir)

    out.note("Analyzing and pricing...")
    view = client.quote_parts(items, zip_code)
    view = client.wait_for_quote(view, items, zip_code, max_wait=MAX_WAIT_S)
    state.remember_zip(zip_code)
    uploaded = [{"part_id": p.part_id, "delete_token": p.delete_token, "file_name": p.file_name, "quote_id": view.quote_id}
                for p in view.parts if p.part_id and p.delete_token]
    state.add_uploads(uploaded, client.base_url)

    result: dict[str, Any] = {"quote": to_jsonable(view)}
    show_quote(out, view)
    if args.checkout and view.is_ready:
        checkout, opened = make_checkout(client, view.quote_id or "", args.open)
        result["checkout"] = {**to_jsonable(checkout), "opened": opened}
        show_checkout(out, checkout, opened)
    if args.delete:
        result["deleted"] = to_jsonable(delete_parts(client, out, [u["part_id"] for u in uploaded]))
    elif uploaded:
        out.line("Files kept for this quote; `mpn delete --all` deletes them.")
    out.data(result)
    return quote_exit(view)


def cmd_requote(args: argparse.Namespace, client: CadClient, out: Out) -> int:
    checked_options(client)
    current = client.get_quote(args.quote_id)
    items = requote_items(current)
    if args.qty is not None or args.material or args.finish:
        items = [QuoteItem(quantity=args.qty or i.quantity, finish=args.finish or i.finish, part_id=i.part_id,
                           units=i.units, material=args.material or i.material) for i in items]
    view = client.update_quote(args.quote_id, items, args.zip or None)
    if view.is_processing:
        zip_code = args.zip or state.last_zip()
        if not zip_code:
            raise UsageError("Pass --zip: the revised parts are still being analyzed.")
        view = client.wait_for_quote(view, items, zip_code, max_wait=MAX_WAIT_S)
    if args.zip:
        state.remember_zip(args.zip)
    show_quote(out, view)
    out.data({"quote": to_jsonable(view)})
    return quote_exit(view)


def make_checkout(client: CadClient, quote_id: str, open_browser: bool) -> tuple[Checkout, bool]:
    checkout = client.create_checkout_link(quote_id)
    opened = False
    if open_browser and checkout.status == "ready" and is_allowed_link(checkout.checkout_url, client.base_url):
        try:
            opened = bool(webbrowser.open(checkout.checkout_url))
        except Exception:  # noqa: BLE001  the link is printed either way
            opened = False
    return checkout, opened


def cmd_checkout(args: argparse.Namespace, client: CadClient, out: Out) -> int:
    checked_options(client)
    checkout, opened = make_checkout(client, args.quote_id, args.open)
    show_checkout(out, checkout, opened)
    out.data({"checkout": {**to_jsonable(checkout), "opened": opened}})
    return EXIT_OK if checkout.status == "ready" else EXIT_NEEDS_INPUT


def delete_parts(client: CadClient, out: Out, part_ids: Sequence[str]) -> Any:
    saved = {u["part_id"]: u for u in state.uploads()}
    missing = [p for p in part_ids if p not in saved]
    if missing:
        raise UsageError(f"No saved upload with id {', '.join(missing)} (see `mpn delete --list`).")
    if not part_ids:
        out.line("Nothing to delete.")
        return {"deleted": [], "errors": []}
    result = client.delete_parts([(p, saved[p]["delete_token"]) for p in part_ids])
    gone = set(result.deleted) | {pid for pid, err in zip(result.error_part_ids, result.errors) if err.code == "PART_NOT_FOUND"}
    state.forget_uploads(gone)
    out.line(f"Deleted {len(result.deleted)} file(s) from Make Parts Now.")
    for pid, err in zip(result.error_part_ids, result.errors):
        out.line(f"  {pid}: {err.message or err.code}")
    return result


def cmd_delete(args: argparse.Namespace, client: CadClient, out: Out) -> int:
    saved = state.uploads()
    if args.list:
        out.data({"uploads": [{k: u[k] for k in ("part_id", "file_name", "quote_id", "uploaded_at") if k in u} for u in saved]})
        for u in saved:
            out.line(f"  {u['part_id']}  {u.get('file_name', '')}  {u.get('uploaded_at', '')[:10]}")
        if not saved:
            out.line("No saved uploads.")
        return EXIT_OK
    if not args.part_ids and not args.all:
        raise UsageError("Name the part ids to delete, or pass --all (see `mpn delete --list`).")
    ids = [u["part_id"] for u in saved] if args.all else list(args.part_ids)
    result = delete_parts(client, out, ids)
    out.data({"deleted": to_jsonable(result)})
    return EXIT_OK


# ------------------------------------------------------------------ entry point


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mpn", description="Instant 3D printing quotes from Make Parts Now (makepartsnow.com).")
    p.add_argument("--version", action="version", version=f"mpn {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    o = sub.add_parser("options", help="list the materials and finishes")
    o.add_argument("--json", action="store_true", help="print JSON")

    q = sub.add_parser("quote", help="quote CAD files (STEP or STL)")
    q.add_argument("files", nargs="+", metavar="FILE[:QTY]", help="files to quote; FILE:QTY sets one file's quantity")
    q.add_argument("--zip", help="US ZIP code the parts ship to (remembered)")
    q.add_argument("--qty", type=int, help="quantity for every file (default 1)")
    q.add_argument("--material", help="material id (default pa12; see `mpn options`)")
    q.add_argument("--finish", help="finish or color id (default the material's first)")
    q.add_argument("--units", choices=("mm", "in"), help="units of STL files (STEP carries its own)")
    q.add_argument("--checkout", action="store_true", help="also make a checkout link")
    q.add_argument("--open", action="store_true", help="open the checkout link in your browser (implies --checkout)")
    q.add_argument("--delete", action="store_true", help="delete the uploads right after quoting")
    q.add_argument("--yes", action="store_true", help="accept what is sent without asking (first run, CI)")
    q.add_argument("--json", action="store_true", help="print JSON")

    r = sub.add_parser("requote", help="revise a quote (new quote id, same files)")
    r.add_argument("quote_id")
    r.add_argument("--qty", type=int)
    r.add_argument("--material")
    r.add_argument("--finish")
    r.add_argument("--zip")
    r.add_argument("--json", action="store_true")

    c = sub.add_parser("checkout", help="make a checkout link for a quote")
    c.add_argument("quote_id")
    c.add_argument("--open", action="store_true", help="open it in your browser")
    c.add_argument("--json", action="store_true")

    d = sub.add_parser("delete", help="delete uploaded files")
    d.add_argument("part_ids", nargs="*")
    d.add_argument("--all", action="store_true", help="every file this computer uploaded")
    d.add_argument("--list", action="store_true", help="list the saved uploads")
    d.add_argument("--json", action="store_true")
    return p


def main(argv: Optional[Sequence[str]] = None, *, transport: Any = None, stdout: TextIO = sys.stdout,
         stderr: TextIO = sys.stderr, ask: Callable[[str], str] = input, interactive: Optional[bool] = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "open", False):
        args.checkout = True
    out = Out(getattr(args, "json", False), stdout, stderr)
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stderr.isatty()
    try:
        if base_url() != DEFAULT_BASE_URL:
            out.note(f"TEST: using {base_url()}")
        client = make_client(transport)
        if args.command == "options":
            return cmd_options(args, client, out)
        if args.command == "quote":
            return cmd_quote(args, client, out, ask, interactive)
        if args.command == "requote":
            return cmd_requote(args, client, out)
        if args.command == "checkout":
            return cmd_checkout(args, client, out)
        return cmd_delete(args, client, out)
    except UsageError as exc:
        out.note(f"mpn: {exc}")
        return EXIT_ERROR
    except CadError as exc:
        out.note(f"mpn: {exc.code}: {exc.message}" if getattr(exc, "message", "") else f"mpn: {exc.code}")
        return EXIT_UNAVAILABLE if exc.code in ("SERVICE_PAUSED", "CLIENT_TOO_OLD") else EXIT_ERROR
    except KeyboardInterrupt:
        out.note("mpn: stopped.")
        return 130
