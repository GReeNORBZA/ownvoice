#!/usr/bin/env bash
# Export a public release tree with fresh history and run the release leak checks.
#
#   scripts/export-release.sh --out DIR --names-file PATH --author "Name <email>" \
#     [--deny-terms PATH] [--release-allow PATH]
#
# The export is `git archive HEAD` minus the internal trees, committed once in a new
# repository (no history). It then runs `ownvoice guard --release` with the private
# names list and, if given, a private deny-terms scan (one term per line: org,
# product, host and tooling names the guard's patterns cannot know). Findings print
# as file paths and counts only. Nothing is pushed.
#
# --release-allow lists names-list tokens reviewed as safe in the public tree (ordinary
# words, synthetic fixture names), one per line. They are dropped for this check only,
# so the names check on generated profiles keeps them.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
out="" names="" deny="" author="" release_allow=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) out="$2"; shift 2 ;;
    --names-file) names="$2"; shift 2 ;;
    --deny-terms) deny="$2"; shift 2 ;;
    --author) author="$2"; shift 2 ;;
    --release-allow) release_allow="$2"; shift 2 ;;
    *) echo "export release: unknown argument $1; expected --out, --names-file, --author, --deny-terms or --release-allow" >&2; exit 2 ;;
  esac
done
fail() { echo "export release [$1]: $2; expected $3; next step: $4" >&2; exit "${5:-2}"; }
[ -n "$out" ] || fail "--out" "missing" "an output directory that does not exist" "supply --out DIR"
[ -n "$names" ] || fail "--names-file" "missing" "the private names list" "supply --names-file PATH"
[[ "$author" =~ ^[^\<]+\ \<[^\>]+@[^\>]+\>$ ]] || fail "--author" "${author:-missing}" \
  "Name <email> for the single public commit" "supply --author \"Name <email>\""
[ -e "$out" ] && fail "$out" "already exists" "a new directory" "remove it or choose another path"
[ -f "$names" ] || fail "$names" "not a file" "the private names list" "check the path"
[ -z "$deny" ] || [ -f "$deny" ] || fail "$deny" "not a file" "a deny-terms file" "check the path"
[ -z "$release_allow" ] || [ -f "$release_allow" ] || fail "$release_allow" "not a file" \
  "a release-allow file" "check the path"
[ -f "$root/.github/workflows/ci.yml" ] || fail "$root/.github/workflows/ci.yml" "missing" \
  "a GitHub Actions workflow to ship" "add .github/workflows/ci.yml before exporting"
git -C "$root" diff --quiet HEAD || fail "$root" "uncommitted changes" "a clean checkout" \
  "commit or stash, then export"

# Internal paths that never ship are listed in .release-exclude, which never ships either.
[ -f "$root/.release-exclude" ] || fail "$root/.release-exclude" "missing" \
  "the list of internal paths to leave out" "create .release-exclude, one path per line"
mapfile -t excluded < <(grep -v -E '^[[:space:]]*(#|$)' "$root/.release-exclude")
excluded+=(.release-exclude)

mkdir -p "$out"
git -C "$root" archive --format=tar HEAD | tar -x -C "$out"
for path in "${excluded[@]}"; do rm -rf "${out:?}/$path"; done
rmdir "$out/docs" 2>/dev/null || true

git -C "$out" init -q -b main
git -C "$out" add -A
git -C "$out" -c user.name="${author% <*}" -c user.email="$(sed -E 's/.*<(.*)>.*/\1/' <<<"$author")" \
  commit -q -m "Initial public release of ownvoice $(sed -nE 's/^version = "(.*)"/\1/p' "$root/pyproject.toml")"
echo "export release [$out]: $(git -C "$out" ls-files | wc -l) files in one commit"

# The release names list: the private list minus release-allowed tokens, with the
# owner's names-allow.txt beside it so the guard still applies that too.
check_dir="$(mktemp -d)"
trap 'rm -rf "$check_dir"' EXIT
chmod 700 "$check_dir"
if [ -n "$release_allow" ]; then
  grep -v -i -x -F -f <(grep -v -E '^[[:space:]]*(#|$)' "$release_allow") "$names" \
    > "$check_dir/names.txt" || true
else
  cp "$names" "$check_dir/names.txt"
fi
allow_beside="$(dirname -- "$names")/names-allow.txt"
[ -f "$allow_beside" ] && cp "$allow_beside" "$check_dir/names-allow.txt"

status=0
echo "export release: guard --release"
if ! (cd "$out" && python3 -m ownvoice guard --tree . --release --names-file "$check_dir/names.txt"); then
  echo "export release [$out]: guard --release failed; fix the paths above before pushing" >&2
  status=5
fi
if [ -n "$deny" ]; then
  echo "export release: deny-terms scan"
  hits="$(cd "$out" && git grep -I -i -c -F -f "$deny" || true)"
  if [ -n "$hits" ]; then
    echo "$hits" | sed 's/^/  deny-term hits: /' >&2
    status=5
  fi
fi
(cd "$out" && python3 -m compileall -q ownvoice) || status=1
[ "$status" -eq 0 ] && echo "export release [$out]: checks passed; review, then push from $out"
exit "$status"
