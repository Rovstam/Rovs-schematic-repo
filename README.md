# schematics

Contains a Python script to know what the Folder name of your schematics correspond in-game 

Learn more about the Repository's naming system at https://docs.google.com/document/d/1kH265N4t_icKoZvsbx4H91VZhlzvv14S?rtpof=true&usp=drive_fs

`python list_schematic_blocks.py` writes the human-readable block catalog to `schematic_blocks.txt`.
Use `python list_schematic_blocks.py --format jsonl` to write a machine-readable index to
`schematic_blocks.jsonl`; each JSON Lines record has a schema version, in-game name, relative
filename, total block count, and per-block counts. Use `--output PATH` to select another output
path. The catalog is only replaced after every schematic has been read successfully.
