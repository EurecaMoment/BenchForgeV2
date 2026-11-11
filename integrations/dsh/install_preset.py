"""Install the three custom presets (or a legacy BenchForge-only patch) into a profile."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import yaml
from profile_migration import migrate_profile, inserted_rows, preset_id, base, replace_entries

Loader, Dumper = base.Loader, base.Dumper


def install(profile, preset):
    current = yaml.load(profile.read_text(encoding='utf-8'), Loader=Loader) or []
    generated = yaml.load(preset.read_text(encoding='utf-8'), Loader=Loader)
    incoming = inserted_rows(generated)
    identities = {preset_id(row) for row in incoming if preset_id(row) is not None}
    if identities == set(base.PRESETS):
        current = migrate_profile(current, generated)
    elif len(incoming) == 1 and identities == {base.BENCHFORGE_ID}:
        current = replace_entries(current, {base.BENCHFORGE_ID: incoming[0]})
    else:
        raise ValueError('Expected all three custom presets or a BenchForge-only compatibility patch')
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = profile.with_name(profile.name + '.before-benchforge-' + timestamp)
    shutil.copy2(profile, backup)
    temporary = profile.with_name(profile.name + '.benchforge-new')
    temporary.write_text(yaml.dump(current, Dumper=Dumper, sort_keys=False, allow_unicode=True),
                          encoding='utf-8')
    shutil.copymode(profile, temporary)
    temporary.replace(profile)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--preset', required=True, type=Path)
    args = parser.parse_args()
    print('Installed custom BenchForge presets; backup:', install(args.profile, args.preset))


if __name__ == '__main__':
    main()
