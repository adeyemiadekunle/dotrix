"""Update one local Compose application without restarting unrelated applications.

Start shared services with pnpm docker:up first. Backend updates apply migrations
before API/worker recreation; database, storage and coding images are not rebuilt.
This helper never targets Dokploy or a remote deployment.
"""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '--project-directory', '.', '--env-file', '.env',
           '-f', 'infra/docker-compose.yml', '-f', 'infra/docker-compose.app.yml']


def commands(component: str) -> list[list[str]]:
    if component == 'backend':
        return [COMPOSE + ['build', 'api'], COMPOSE + ['run', '--rm', '--no-deps', 'migrate'],
                COMPOSE + ['up', '-d', '--no-deps', 'api', 'worker']]
    if component not in {'web', 'admin', 'site'}:
        raise ValueError('Unknown local application')
    return [COMPOSE + ['up', '-d', '--no-deps', '--build', component]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['backend', 'web', 'admin', 'site'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    for argv in commands(args.component):
        print(' '.join(argv), flush=True)
        if not args.dry_run:
            subprocess.run(argv, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
