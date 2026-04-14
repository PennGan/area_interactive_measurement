# Sequential Rename Script

`sequential_rename.py` renames files or directories in a target folder based on
their current names sorted in ascending order.

The new naming format is:

```text
<prefix><number>
```

For files, the original file extension is kept.

## Use Cases

- Rename image files in a folder to a clean numeric sequence
- Rename subfolders in a fixed order
- Preview the rename result before making changes

## Requirements

- Python 3

## Usage

```bash
python3 sequential_rename.py TARGET_DIR PREFIX START_NUMBER
```

Example:

```bash
python3 sequential_rename.py \
"/Volumes/Colorful/Work/Research_Projects_Archives/2026/Phenotype/1_Arabidopsis_phenotype" \
Arabidopsis_ 1
```

This will rename files in that folder, sorted by current filename from small to
large, to:

```text
Arabidopsis_1.xxx
Arabidopsis_2.xxx
Arabidopsis_3.xxx
...
```

## Options

Rename only directories:

```bash
python3 sequential_rename.py TARGET_DIR PREFIX START_NUMBER --type dirs
```

Rename both files and directories:

```bash
python3 sequential_rename.py TARGET_DIR PREFIX START_NUMBER --type all
```

Preview only, without applying changes:

```bash
python3 sequential_rename.py TARGET_DIR PREFIX START_NUMBER --dry-run
```

## Notes

- Sorting is based on the current entry name in ascending order.
- File renaming keeps the original suffix such as `.jpg`, `.png`, or `.tif`.
- Directory renaming does not add a suffix.
- The script uses a two-step rename flow internally to avoid name collisions.
