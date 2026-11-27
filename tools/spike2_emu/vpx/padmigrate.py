"""Move a table prepared for the upstream PAD.Controller to this app's own.

Tables prepared by SPIKE 2 VPX 0.1.0 create PAD.Controller, which Windows
gives to whichever app registered it last (see controller_id.py). Play moves
such a table to Spike2Vpx.Controller where it is, once, so it never has to be
prepared again from its download:

- a scripted table (vpxshadow) creates the controller in its own script, which
  is rewritten and the table re-signed, like vpxsounds.quiet_in_place;
- a ROM table loads PADSPIKE2.vbs from its folder, which is replaced with this
  app's copy (preparing a table already does that).
"""

import os
import re
import shutil

import controller_id

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = "PADSPIKE2.vbs"

#: The legacy name where a script creates the controller or names it in the
#: message shown when that fails. Other mentions (comments) are left as they are.
_LEGACY = re.compile(r'(CreateObject\(\s*"|Can\'t load )%s\b' % re.escape(controller_id.LEGACY_PROGID),
                     re.I)


def moved(script):
    """*script* creating this app's controller instead of the legacy one."""
    return _LEGACY.sub(lambda m: m.group(1) + controller_id.PROGID, script)


def legacy(script):
    return bool(_LEGACY.search(script))


def controller_in_place(path, script):
    """Move the table at *path*, whose embedded script is *script*, and its
    helper to this app's controller. Returns report lines, [] when there was
    nothing to do. Raises OSError when the table or its folder cannot be
    written."""
    rep = []
    if legacy(script):
        import vpxfile

        # The script as vpxfile reads and writes it, so nothing else in it changes.
        table = vpxfile.VpxTable(path)
        try:
            exact = table.script()
        finally:
            table.ole.close()
        tmp = path + ".pad-controller.tmp"
        vpxfile.write_patched(path, tmp, script=moved(exact))
        check = vpxfile.VpxTable(tmp)
        ok = check.verify()
        check.ole.close()
        if not ok:
            os.remove(tmp)
            raise OSError("%s does not verify with the new controller name; it was left as it was. "
                          "Choose the original VPX file to prepare a new copy." % os.path.basename(path))
        os.replace(tmp, path)
        rep.append("controller: %s now creates %s" % (os.path.basename(path), controller_id.PROGID))
    helper = os.path.join(os.path.dirname(path), HELPER)
    if HELPER.lower() in script.lower() and os.path.isfile(helper):
        with open(helper, encoding="utf-8", errors="replace") as f:
            old = legacy(f.read())
        if old:
            shutil.copyfile(os.path.join(HERE, HELPER), helper)
            rep.append("controller: %s beside it replaced with this app's copy" % HELPER)
    return rep
