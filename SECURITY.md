# Security

Please report a vulnerability in `mpn`, or in how it talks to makepartsnow.com, by email to
nathan@makepartsnow.com with "security" in the subject. Don't open a public issue. We answer within 3 business days.

What the tool does to stay small and safe:

- It talks only to makepartsnow.com over HTTPS with certificate checks (plain HTTP only to localhost, for development).
- It opens in the browser, and uploads files to, only https links on makepartsnow.com (or the configured development
  server), whatever a server answer names.
- It has no dependencies beyond Python's standard library and never runs downloaded code.
- It never sees payment details (checkout is on makepartsnow.com through Stripe). It keeps only your consent, last ZIP
  code and your uploads' delete tokens on this computer, in files readable only by you.

Supported versions: the latest release.
