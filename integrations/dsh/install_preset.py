"""Install the two BenchForge presets into a profile."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import yaml
from profile_migration import migrate_profile, base

Loader, Dumper = base.Loader, base.Dumper


def install(profile, preset):
    current = yaml.load(profile.read_text(encoding='utf-8'), Loader=Loader) or []
    generated = yaml.load(preset.read_text(encoding='utf-8'), Loader=Loader)
    current = migrate_profile(current, generated)
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
