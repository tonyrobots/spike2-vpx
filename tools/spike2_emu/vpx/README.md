# Visual Pinball X kit

`padvpx.py tables` lists the bundled SPIKE 2 table maps. Run
`padvpx.py patch <table.vpx>` on a matching table to create a separate
`(PAD)` copy. The kit writes the associated `PADSPIKE2.vbs` into the output
folder. Godzilla LE uses `godzilla_le.vpxmap.json` and the Godzilla patcher.

Use the [Setup window](../../../README.md#set-up) to register the bundled
`Spike2Vpx.Controller` (upstream's is `PAD.Controller`; `controller_id.py` says
why this fork has its own). Use `Play-Spike2Vpx.ps1` to start the game before opening the
table and to stop the game when VPX exits.
