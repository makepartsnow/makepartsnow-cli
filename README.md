# makepartsnow: instant 3D printing quotes for CAD files, from the command line

`mpn` quotes your STEP and STL files with [Make Parts Now](https://makepartsnow.com), a US 3D printing service, and gives you a link to order and pay on makepartsnow.com. SLS PA12 nylon (gray or black dyed) or FDM plastics (PLA, PETG, ABS, ASA, TPU, carbon-fiber nylon and PETG) in their colors, each file with its own quantity, one delivered price before tax. No account, no API key, no dependencies.

Useful when you design parts in code (CadQuery, build123d, OpenSCAD) or export them from any CAD tool and want a price for each revision without opening a browser.

```console
$ pip install makepartsnow
$ mpn quote bracket.step:10 cover.stl --units mm --zip 89101 --finish black
Quote quote_7Hq...: ready
  Bracket.step  40 x 20 x 6 mm  PA12 Nylon (Formlabs Nylon 12), black  10 x $2.96 = $29.60
  Cover.stl  24 x 24.8 x 18.9 mm  PA12 Nylon (Formlabs Nylon 12), black  1 x $3.41 = $3.41
  Parts $33.01  shipping $6.56
  Total $39.57 before tax, Standard speed
  Ships by 2026-10-21, arrives by 2026-10-28
  https://makepartsnow.com/quotes/share/...
```

Requires Python 3.11 or newer.

## Commands

| Command | What it does |
|---|---|
| `mpn options` | The materials, finishes and colors you can choose, with their build volumes |
| `mpn quote FILE[:QTY]... --zip ZIP` | Uploads the files and prices them as one order. `--qty`, `--material` and `--finish` apply to every file; `FILE:QTY` sets one file's quantity. STL files need `--units mm` or `--units in` (STEP carries its own) |
| `mpn quote ... --checkout` / `--open` | Also makes a checkout link (`--open` opens it in your browser). You review the order and pay on makepartsnow.com; `mpn` never pays |
| `mpn requote QUOTE_ID --qty N` | A revised quote with a new quantity, material, finish or ZIP, reusing the uploaded files |
| `mpn checkout QUOTE_ID [--open]` | A checkout link for an existing quote |
| `mpn delete --all` / `mpn delete PART_ID` / `mpn delete --list` | Deletes files you uploaded (the CLI keeps their delete tokens on this computer) |

Add `--json` to any command for one JSON object a script can read. Exit codes: 0 a ready quote, 2 a quote that needs input (a part too big for the material, units to confirm) or a person's review, 3 quoting is paused or this version is too old, 1 any other error.

Up to 25 files and 10,000 of each per quote, Standard speed, US shipping only. Prices are in USD before sales tax; tax is added at checkout.

## What it sends, and where

- **Only to makepartsnow.com:** each file you name, the quantity, material and finish you choose, and the ZIP code. A STEP file is sent as a copy whose header has the author, organization and file path blanked; your file is never changed.
- **Nothing else:** no other files, no account, no telemetry. The requests carry the User-Agent `MakePartsNow-CLI/<version>` and `?client=cli`, so Make Parts Now knows the quote came from this tool.
- **The first quote asks first** on a terminal. In CI or a script, pass `--yes` or set `MPN_ACCEPT=1`.
- **Your files on the server** are stored encrypted and deleted automatically under the [privacy policy](https://makepartsnow.com/legal/privacy); `mpn delete --all` deletes them sooner. Files on an order stay with it. Uploads are tied to your network address: the quote ids work from the address that uploaded them, and the delete tokens work from anywhere.
- **On this computer:** `settings.json` (that you accepted, and your last ZIP) and `uploads.json` (the part ids and delete tokens of your uploads), readable only by you, in `%APPDATA%\makepartsnow`, `~/Library/Application Support/makepartsnow` or `~/.config/makepartsnow` (`MPN_CONFIG_DIR` moves it).
- **Money:** nothing is charged here. A checkout link opens Stripe Checkout on makepartsnow.com; anyone with the link can open it and pay for that quote, though they can't change it.

TLS is always verified. Links are opened, and files uploaded, only on makepartsnow.com.

## How it works

`mpn` is a thin command-line host for the [Make Parts Now CAD core](https://github.com/makepartsnow/makepartsnow-cad-core), the same client the Fusion add-in and the [FreeCAD workbench](https://github.com/makepartsnow/makepartsnow-freecad) use, vendored in `src/makepartsnow/core/` (pinned in `CORE_PIN.json`). It talks to the hosted `https://makepartsnow.com/mcp/cad` endpoint. `MPN_BASE_URL` points it at a development server (https, or http to localhost).

## Develop

```bash
python -m pip install pytest
python -m pytest
```

To update the core: in a checkout of makepartsnow-cad-core, `scripts/sync-core.py <this repo>/src/makepartsnow/core`.

## Support

- Orders and questions: orders@makepartsnow.com or [makepartsnow.com/contact](https://makepartsnow.com/contact)
- Other ways to connect (AI assistants, CAD add-ins, the REST API): [makepartsnow.com/developers](https://makepartsnow.com/developers)
- Problems with this tool: open an issue. Report security problems privately (see [SECURITY.md](SECURITY.md)).

## License

MIT, for this code. The Make Parts Now service is covered by its [terms](https://makepartsnow.com/legal/terms).
