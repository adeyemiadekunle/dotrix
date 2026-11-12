#!/usr/bin/env bash
# Database migrations for a deployed dotrix, run on the server where its containers run.
#
# Every deploy already applies migrations: the compose file's `migrate` service runs
# `alembic upgrade head` before the API and worker start. Use this script to see where the
# database stands, to back it up before a deploy, to apply migrations again after a failed
# deploy, or to check that a deploy left it current.
#
#   deploy/migrate.sh status    where the database is, and what is waiting to be applied
#   deploy/migrate.sh backup    a pg_dump of the database into $BACKUP_DIR (default ./backups)
#   deploy/migrate.sh upgrade   apply what is waiting (refuses when the code has two heads)
#   deploy/migrate.sh check     exit 0 only when the database is at the code's single head
#   deploy/migrate.sh           all of it: status, backup, upgrade (after you confirm), check
#
# Options (environment variables):
#   IMAGE             run the migrations from this backend image (the release being deployed, e.g.
#                     dotrix-backend:0.2.0) in a one-off container, instead of in the running API.
#                     Use it when a deploy failed at `migrate`: the API still running then is the
#                     previous release, whose code knows only the previous migrations.
#   COMPOSE_PROJECT   the compose project's name, when more than one dotrix runs on this host
#   API_CONTAINER     the API container, instead of finding it by its compose labels
#   PG_CONTAINER      the Postgres container, likewise
#   PG_NETWORK        with IMAGE: the Docker network Postgres is on (default: its first)
#   DOTRIX_DATABASE_URL  with IMAGE and no API running: the database URL (otherwise the API's is used)
#   BACKUP_DIR        where backups go (default ./backups)
#   YES=1             upgrade without asking
#
# It finds the running containers by their compose labels, so it works from any directory and
# needs neither the compose file nor its env file. Migrations run inside the API container,
# which has the code and DOTRIX_DATABASE_URL; backups run inside the Postgres container.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-./backups}
DB_USER=${DB_USER:-dotrix}
DB_NAME=${DB_NAME:-dotrix}

say() { printf '%s\n' "$*"; }
die() { printf 'migrate.sh: %s\n' "$*" >&2; exit 1; }

find_container() {
  local service=$1
  local filters=(--filter "label=com.docker.compose.service=$service" --filter status=running)
  [[ -n ${COMPOSE_PROJECT:-} ]] && filters+=(--filter "label=com.docker.compose.project=$COMPOSE_PROJECT")
  local found
  found=$(docker ps "${filters[@]}" --format '{{.Names}}')
  [[ -n $found ]] || die "no running '$service' container found (is dotrix up? set COMPOSE_PROJECT or ${service^^}_CONTAINER)"
  if [[ $(wc -l <<<"$found") -gt 1 ]]; then
    die "more than one running '$service' container: $(tr '\n' ' ' <<<"$found")— set COMPOSE_PROJECT"
  fi
  printf '%s' "$found"
}

api() { API_CONTAINER=${API_CONTAINER:-$(find_container api)}; printf '%s' "$API_CONTAINER"; }
pg() { PG_CONTAINER=${PG_CONTAINER:-$(find_container postgres)}; printf '%s' "$PG_CONTAINER"; }

pg_network() {
  PG_NETWORK=${PG_NETWORK:-$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}' "$(pg)" | head -1)}
  printf '%s' "$PG_NETWORK"
}

alembic() {
  if [[ -n ${IMAGE:-} ]]; then
    local url=${DOTRIX_DATABASE_URL:-} network
    [[ -n $url ]] || url=$(docker exec "$(api)" printenv DOTRIX_DATABASE_URL 2>/dev/null) || true
    [[ -n $url ]] || die "with IMAGE and no running API, set DOTRIX_DATABASE_URL"
    network=$(pg_network)
    [[ -n $network ]] || die "couldn't find Postgres's Docker network: set PG_NETWORK"
    # The URL goes to the container by name (-e NAME), so it never appears in the process list.
    DOTRIX_DATABASE_URL=$url docker run --rm -e DOTRIX_DATABASE_URL --network "$network" -w /app/apps/backend \
      "$IMAGE" alembic "$@"
  else
    docker exec -w /app/apps/backend "$(api)" alembic "$@"
  fi
}

code_source() { if [[ -n ${IMAGE:-} ]]; then printf 'image %s' "$IMAGE"; else printf 'the running API (%s)' "$(api)"; fi; }

# The revision ids alone, one per line (alembic prints "<id> (head)" and similar).
revisions() { awk '/^[0-9a-f]{6,}/ {print $1}'; }

# Alembic's own chatter (its INFO lines) is dropped; a failure is shown, then stops the script.
quiet() {
  local out
  if ! out=$(alembic "$@" 2>&1); then
    printf '%s\n' "$out" | grep -v '^INFO ' >&2
    die "alembic $1 failed"
  fi
  printf '%s\n' "$out"
}
current() { quiet current | revisions; }
heads() { quiet heads | revisions; }

status() {
  local now head
  now=$(current); head=$(heads)
  say "Database:  ${now:-(empty: no migration applied yet)}"
  say "Code head: $(tr '\n' ' ' <<<"$head")(from $(code_source))"
  if [[ $(wc -l <<<"$head") -gt 1 ]]; then
    say "The code has more than one head: join them with a merge migration before deploying."
    return 2
  fi
  if [[ -n $now && $now == "$head" ]]; then
    say "Up to date."
  else
    say "Waiting to be applied:"
    # The range starts at the current revision itself: leave out the step that reached it.
    alembic history -r "${now:-base}:head" | grep -v -- "-> ${now:-none}," | sed 's/^/  /'
  fi
}

backup() {
  mkdir -p "$BACKUP_DIR"
  local file
  file="$BACKUP_DIR/dotrix-$(date -u +%Y%m%dT%H%M%SZ).dump"
  say "Backing up '$DB_NAME' to $file ..."
  docker exec "$(pg)" pg_dump -U "$DB_USER" -d "$DB_NAME" --format=custom >"$file"
  [[ -s $file ]] || die "the backup is empty: $file"
  say "Done ($(du -h "$file" | cut -f1)). To restore it (this replaces the database's contents):"
  say "  docker exec -i $(pg) pg_restore -U $DB_USER -d $DB_NAME --clean --if-exists < $file"
}

upgrade() {
  [[ $(heads | wc -l) -eq 1 ]] || die "the code has more than one migration head; refusing to upgrade"
  say "Applying migrations ..."
  alembic upgrade head
}

check() {
  local now head
  now=$(current); head=$(heads)
  if [[ $(wc -l <<<"$head") -eq 1 && -n $now && $now == "$head" ]]; then
    say "OK: the database is at $head."
  else
    die "the database ($now) is not at the code's head ($(tr '\n' ' ' <<<"$head"))"
  fi
}

command -v docker >/dev/null || die "docker isn't installed here: run this on the server where dotrix runs"

case ${1:-all} in
  status) status ;;
  backup) backup ;;
  upgrade) upgrade ;;
  check) check ;;
  all)
    status || die "fix the migration heads first"
    if [[ $(current) == "$(heads)" ]]; then exit 0; fi
    backup
    if [[ ${YES:-} != 1 ]]; then
      read -r -p "Apply these migrations now? [y/N] " answer
      [[ $answer == [yY]* ]] || die "nothing applied"
    fi
    upgrade
    check
    ;;
  -h | --help | help) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$1' (status, backup, upgrade, check, or none for all of them)" ;;
esac
