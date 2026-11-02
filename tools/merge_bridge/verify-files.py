"""Validate one complete game profile before developer compilation; never attach."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from bongo_chat.merge_install import validate_game_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, required=True)
    args = parser.parse_args()
    contract = json.loads(Path(__file__).with_name('local-contract.json').read_text(encoding='utf-8'))
    print(json.dumps(validate_game_files(args.game_root, contract)))


if __name__ == '__main__':
    main()
