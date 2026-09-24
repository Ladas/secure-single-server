#!/usr/bin/env bash

set -euo pipefail

TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly TEST_DIR
REPO_DIR="$(cd -- "${TEST_DIR}/.." && pwd)"
readonly REPO_DIR

cd "${REPO_DIR}"

# shellcheck source=scripts/common/lib.sh
source "${REPO_DIR}/scripts/common/lib.sh"
[[ "$(selinux_path_regex /etc/praxis/shared-gateway.yaml)" == '^/etc/praxis/shared-gateway\.yaml$' ]] ||
  die "SELinux path escaping failed"
bash "${TEST_DIR}/shared-gateway-unit.sh"

mapfile_compat() {
  while IFS= read -r line; do
    printf '%s\0' "${line}"
  done
}

shell_files=()
while IFS= read -r -d '' file; do
  shell_files+=("${file}")
done < <(find scripts tests -type f -name '*.sh' -print | sort | mapfile_compat)
while IFS= read -r -d '' file; do
  shell_files+=("${file}")
done < <(find scripts/common scripts/all-in-one scripts/remote-gateway -type f ! -name '*.sh' ! -name credentials -print | sort | mapfile_compat)

for file in "${shell_files[@]}"; do
  bash -n "${file}"
done

# Bash 3.2 does not reliably apply errexit to bare [[ ... ]] assertions.
# All assertions must handle failure explicitly, including multiline ones.
if rg -n '\]\][[:space:]]*$' "${shell_files[@]}"; then
  die "bare conditional assertion: add an explicit failure handler"
fi

if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --version
  shellcheck -x "${shell_files[@]}"
else
  printf 'warning: shellcheck is not installed; skipped\n' >&2
fi

for file in configs/all-in-one/clients/*.json; do
  jq empty "${file}" >/dev/null
done

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

awk '
  FNR == NR {
    if ($0 == "filter_chains:") { capture = 1; next }
    if (capture) baseline = baseline $0 ORS
    next
  }
  /# @@BASELINE_FILTER_CHAINS@@/ { printf "%s", baseline; next }
  { print }
' configs/all-in-one/shared-gateway.yaml \
  configs/all-in-one/shared-gateway-switchyard.yaml.in >"${tmp_dir}/switchyard.yaml"
sed -i.bak \
  -e 's/@@JUDGE_MODEL@@/judge-model/g' \
  -e 's/@@WEAK_MODEL@@/weak-model/g' \
  -e 's/@@STRONG_MODEL@@/strong-model/g' \
  "${tmp_dir}/switchyard.yaml"
rm -f "${tmp_dir}/switchyard.yaml.bak"

ruby -rpsych -e 'ARGV.each { |path| Psych.parse_stream(File.read(path), filename: path) }' \
  configs/remote-gateway/gateway.yaml configs/remote-gateway/policy.yaml \
  configs/all-in-one/shared-gateway.yaml \
  configs/all-in-one/shared-gateway-valkey.yaml \
  "${tmp_dir}/switchyard.yaml" \
  .github/workflows/validate.yml

for profile in memory valkey; do
  render_remote_config "${profile}" configs/remote-gateway/gateway.yaml "${tmp_dir}/remote-${profile}.yaml"
done
render_remote_quadlet configs/common/quadlet/praxis-valkey-backend.container.in "${tmp_dir}/remote.container"
[[ "$(grep '^PublishPort=' "${tmp_dir}/remote.container")" == 'PublishPort=0.0.0.0:8443:8443' ]] ||
  die "remote Quadlet must publish only TLS"
[[ "$(grep -c '^Volume=/etc/praxis/.*:ro$' "${tmp_dir}/remote.container")" == 5 ]] ||
  die "remote Quadlet must mount its five protected runtime files read-only"
ruby -ryaml -e '
  ARGV.each do |path|
    config = YAML.load_file(path)
    listeners = config.fetch("listeners")
    abort "remote listener is not TLS-only" unless listeners.size == 1 && listeners[0].key?("tls")
    filters = config.fetch("filter_chains")[0].fetch("filters")
    kinds = filters.map { |filter| filter.fetch("filter") }
    abort "authentication must precede credential removal" unless kinds.index("policy") < kinds.index("headers")
    quotas = filters.select { |filter| filter["filter"] == "token_rate_limit" }
    expected = path.include?("valkey") ? "valkey" : "memory"
    abort "unexpected quota backend" unless quotas.size == 2 && quotas.all? { |q| q["backend"]["kind"] == expected }
  end
' "${tmp_dir}/remote-memory.yaml" "${tmp_dir}/remote-valkey.yaml"

markdown_files=(README.md)
while IFS= read -r file; do
  markdown_files+=("${file}")
done < <(find docs -type f -name '*.md' -print | sort)

# The single-quoted program is Ruby; Markdown backticks are not shell syntax.
# shellcheck disable=SC2016
ruby -e '
  require "open3"
  ARGV.each do |source|
    content = File.read(source, encoding: "UTF-8")
    content.scan(/\]\(([^)#]+)(?:#[^)]+)?\)/).flatten.each do |link|
      next if link.match?(%r{^[a-z]+://})
      target = File.expand_path(link, File.dirname(source))
      abort "missing Markdown link target: #{source} -> #{link}" unless File.exist?(target)
    end
    content.scan(/^```(?:console|sh|bash)\n(.*?)^```/m).each_with_index do |(code), index|
      _, error, status = Open3.capture3("bash", "-n", stdin_data: code)
      abort "invalid shell block #{index + 1} in #{source}: #{error}" unless status.success?
    end
  end
' "${markdown_files[@]}"

[[ -f docs/quickstarts/all-in-one/users.md ]] || die "user workflow is missing"
[[ -f docs/testing/README.md ]] || die "testing index is missing"
[[ -f docs/testing/harnesses.md ]] || die "harness acceptance guide is missing"
for file in docs/quickstarts/all-in-one/in-memory.md docs/quickstarts/all-in-one/valkey.md docs/quickstarts/all-in-one/switchyard.md; do
  rg -q '^## 1\. Transfer the administrator deployment bundle$' "${file}"
  rg -q 'configs/all-in-one configs/common' "${file}"
  if rg -q 'git clone' "${file}"; then
    printf 'deployment quickstart clones the repository on RHEL: %s\n' "${file}" >&2
    exit 1
  fi
done
if rg -n 'developer-workflow|quickstart-(persistent|podman|switchyard|valkey)|testing-(fedora-coreos|rhel-vm)' README.md docs; then
  printf 'obsolete documentation path found\n' >&2
  exit 1
fi

if rg -n 'Network=host|PublishPort=(?!127\.0\.0\.1:)' configs/common/quadlet --pcre2; then
  printf 'unsafe host networking or publish address found\n' >&2
  exit 1
fi
if rg -n 'PublishPort=.*:(9901|6379|8000)(:|$)' configs/common/quadlet; then
  printf 'private admin or dependency port is published\n' >&2
  exit 1
fi
if rg -n '^Volume=/etc/praxis/.*:Z$' configs/common/quadlet; then
  printf 'rootless Quadlet must not relabel root-owned /etc/praxis files\n' >&2
  exit 1
fi

for file in configs/common/quadlet/*.container.in; do
  rg -q '^Pull=never$' "${file}"
  rg -q '^ReadOnly=true$' "${file}"
  rg -q '^NoNewPrivileges=true$' "${file}"
  rg -q '^DropCapability=all$' "${file}"
  unsupported="$(awk '
    /^\[Container\]$/ { in_container = 1; next }
    /^\[/ { in_container = 0 }
    in_container && /^[A-Za-z][A-Za-z]+=/ {
      key = $0
      sub(/=.*/, "", key)
      if (key !~ /^(Image|ContainerName|Pull|User|Group|UserNS|Network|PublishPort|Volume|Secret|ReadOnly|NoNewPrivileges|DropCapability|HealthOnFailure|Exec)$/) {
        print key
      }
    }
  ' "${file}")"
  [[ -z "${unsupported}" ]] || {
    printf 'unsupported Podman 4.6 Quadlet key in %s: %s\n' "${file}" "${unsupported}" >&2
    exit 1
  }
done

rg -q '^User=1001$' configs/common/quadlet/praxis*.container.in
rg -q '^User=999$' configs/common/quadlet/praxis-valkey.container.in
rg -q '^WantedBy=default.target$' configs/common/quadlet/*.container.in
rg -q 'session_floor: disabled' "${tmp_dir}/switchyard.yaml"
rg -q 'on_failure: closed' "${tmp_dir}/switchyard.yaml"

token_line="$(rg -n -m1 'filter: token_rate_limit' configs/all-in-one/shared-gateway-switchyard.yaml.in | cut -d: -f1)"
judge_line="$(rg -n -m1 'filter: switchyard_route' configs/all-in-one/shared-gateway-switchyard.yaml.in | cut -d: -f1)"
(( token_line < judge_line )) || {
  printf 'Switchyard token admission must precede its judge call\n' >&2
  exit 1
}

if rg -n '(sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{25,})' \
  configs docs README.md; then
  printf 'possible committed credential found\n' >&2
  exit 1
fi

git diff --check
printf 'static shared-gateway checks passed\n'
