# Changelog

## 0.1.0 (2026-10-18)

- First release. `mpn options`, `quote`, `requote`, `checkout` and `delete`, with `--json` and exit codes for scripts.
- Quotes 1 to 25 STEP or STL files as one order (SLS PA12 or the offered FDM plastics, Standard speed) on
  `https://makepartsnow.com/mcp/cad?client=cli`; STEP files are sent as copies with the header's author,
  organization and path blanked.
- Built on the vendored Make Parts Now CAD core 0.1.4. No dependencies; Python 3.11+.
