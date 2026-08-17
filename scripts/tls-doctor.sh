#!/usr/bin/env bash
set -u

host=${TLS_TEST_HOST:-pypi.org}
url=${TLS_TEST_URL:-https://pypi.org/simple/}
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

ok=0
warn=0
fail=0
pass() { printf 'PASS  %s\n' "$*"; ok=$((ok + 1)); }
warning() { printf 'WARN  %s\n' "$*"; warn=$((warn + 1)); }
failure() { printf 'FAIL  %s\n' "$*"; fail=$((fail + 1)); }

printf 'TLS doctor for %s\n\n' "$url"

if command -v docker >/dev/null 2>&1; then
  pass "docker: $(docker --version 2>/dev/null | head -1)"
  if docker compose version >/dev/null 2>&1; then
    pass "docker compose: $(docker compose version 2>/dev/null | head -1)"
  else
    failure "docker compose plugin is unavailable"
  fi
else
  failure "docker is not installed or not on PATH"
fi

proxy_names=()
for name in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy ALL_PROXY all_proxy; do
  [[ -n "${!name:-}" ]] && proxy_names+=("$name")
done
if ((${#proxy_names[@]})); then
  pass "proxy environment present: ${proxy_names[*]} (values redacted)"
else
  warning "no proxy environment variables are set"
fi

if command -v getent >/dev/null 2>&1; then
  if getent ahosts "$host" >/dev/null 2>&1; then
    pass "DNS resolves $host"
  else
    failure "DNS cannot resolve $host; this is not a certificate error"
  fi
elif command -v nslookup >/dev/null 2>&1; then
  if nslookup "$host" >/dev/null 2>&1; then pass "DNS resolves $host"; else failure "DNS cannot resolve $host"; fi
else
  warning "no getent/nslookup available; DNS check skipped"
fi

if command -v curl >/dev/null 2>&1; then
  curl_log=$(mktemp)
  if curl --fail --silent --show-error --head --max-time 12 "$url" >/dev/null 2>"$curl_log"; then
    pass "curl verifies HTTPS using the machine trust/proxy configuration"
  else
    msg=$(tr '\n' ' ' <"$curl_log" | sed 's/[[:space:]]\+/ /g')
    case "$msg" in
      *"certificate"*|*"SSL"*|*"TLS"*) failure "curl TLS verification failed: $msg" ;;
      *"resolve host"*|*"Could not resolve"*) failure "curl failed DNS resolution: $msg" ;;
      *"proxy"*|*"CONNECT"*) failure "curl proxy connection failed: $msg" ;;
      *) failure "curl HTTPS request failed: $msg" ;;
    esac
  fi
  rm -f "$curl_log"
else
  warning "curl is unavailable"
fi

if command -v python3 >/dev/null 2>&1; then
  py_out=$(python3 - "$url" <<'PY' 2>&1
import sys, ssl, urllib.request
url = sys.argv[1]
print("verify_paths=", ssl.get_default_verify_paths())
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        print("status=", r.status)
except Exception as exc:
    print(type(exc).__name__ + ":", exc)
    raise
PY
)
  if [[ $? -eq 0 ]]; then
    pass "Python stdlib verifies HTTPS"
  else
    failure "Python HTTPS verification failed: $(echo "$py_out" | tail -1)"
  fi
else
  warning "python3 is unavailable"
fi

cert_count=0
bad_count=0
for cert in "$repo_root"/docker/certs/*.crt; do
  [[ -e "$cert" ]] || continue
  cert_count=$((cert_count + 1))
  blocks=$(grep -c 'BEGIN CERTIFICATE' "$cert" 2>/dev/null || true)
  if [[ "$blocks" -ne 1 ]]; then
    failure "$(basename "$cert") contains $blocks certificates; Debian requires one certificate per .crt file"
    bad_count=$((bad_count + 1))
    continue
  fi
  if ! openssl x509 -in "$cert" -noout >/dev/null 2>&1; then
    failure "$(basename "$cert") is not a valid PEM X.509 certificate"
    bad_count=$((bad_count + 1))
    continue
  fi
  if ! openssl x509 -in "$cert" -noout -text | grep -A1 'Basic Constraints' | grep -q 'CA:TRUE'; then
    failure "$(basename "$cert") is not a CA certificate (CA:TRUE missing)"
    bad_count=$((bad_count + 1))
  fi
done
if [[ $cert_count -eq 0 ]]; then
  warning "no corporate CA is staged in docker/certs/"
elif [[ $bad_count -eq 0 ]]; then
  pass "$cert_count staged CA certificate(s) are structurally valid"
fi

printf '\nSummary: %d pass, %d warning, %d fail\n' "$ok" "$warn" "$fail"
if ((fail)); then
  cat <<'TXT'

Interpretation:
- DNS failures must be fixed before TLS can be diagnosed.
- Proxy/CONNECT failures indicate proxy configuration, not a CA-chain problem.
- Certificate verification failures require the corporate root/issuing CA to be
  trusted by the host and copied into docker/certs/ for container builds.
TXT
  exit 1
fi
