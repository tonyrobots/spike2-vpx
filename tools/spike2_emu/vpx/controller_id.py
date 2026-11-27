"""The COM identity tables use to reach SPIKE 2 VPX's controller.

SPIKE 2 VPX is a fork of Pinball Asset Decryptor, which registers its own
controller as PAD.Controller. Windows keeps one registration per name, so the
two apps took the name from each other and tables ran whichever copy was
registered last. SPIKE 2 VPX therefore has its own name and class ID.
Everything that registers, checks, creates or patches in the controller takes
them from here (PADSPIKE2.vbs is a static file; a test keeps it in step).
"""

PROGID = "Spike2Vpx.Controller"
CLSID = "{8A4F0C9B-1D04-4224-A053-8A15F625E1CD}"

#: The upstream identity this fork used up to 0.1.0. Tables prepared then
#: create it, and are moved to PROGID where they are (padmigrate).
LEGACY_PROGID = "PAD.Controller"
LEGACY_CLSID = "{7D5B2A1E-6C3F-4B8A-9E21-5A2F0C7D9B11}"
