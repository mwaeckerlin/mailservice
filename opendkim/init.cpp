/**

OpenDKIM init: minimal, shell-free entrypoint for the opendkim container.

Replaces the previous start.sh (and opendkim-genkey/Perl) with a small,
statically linked C++ helper. Follows the same idea as mwaeckerlin/nginx's
envwrap: parse env, do the setup, execvp() the actual daemon. The runtime
image therefore contains no /bin/sh and no Perl.

Behavior (identical to the old start.sh):

  1. DOMAINS is a space-separated list of domains; falls back to the single
     DOMAIN env var. If both are empty, exit with an error.
  2. SELECTOR is the DKIM selector (DNS label), default "mail".
  3. Truncate /etc/opendkim/KeyTable and /etc/opendkim/SigningTable.
  4. For each domain:
       - If /etc/opendkim/keys/<domain>/<selector>.private is missing,
         create the key directory and generate a 2048-bit RSA key by
         forking `openssl genrsa`, extract the public key with
         `openssl rsa -pubout`, strip PEM armor + newlines, and write the
         BIND-style TXT record next to the key. Also print the record to
         stdout so it can be copy-pasted into DNS.
       - Append one line to KeyTable and one to SigningTable so opendkim
         signs *@<domain> with <selector>._domainkey.<domain>.
  5. (Re)write /etc/opendkim/TrustedHosts with loopback + RFC1918.
  6. Compose /run/opendkim/opendkim.conf from /etc/opendkim.conf.base plus
     the mode selected by DKIM_DMARC — a single knob with four levels:
       - off        : Mode "s" — sign only, do NOT verify incoming, add no
                      Authentication-Results header. The filter is
                      effectively disabled for inbound traffic.
       - log        : Mode "sv" + AlwaysAddARHeader true — verify every
                      incoming signature and stamp the verdict into an
                      Authentication-Results header, but never reject.
                      This is the monitor mode operators run before
                      switching to actual enforcement.
       - permissive : Mode "sv" + On-BadSignature and On-KeyNotFound set
                      to reject (subject to DKIM_KEYERROR_ACTION, which
                      may lower the KeyNotFound path to tempfail). Mail
                      without any DKIM signature is accepted — this is
                      the "DKIM is optional, but if you publish it it
                      must be correct" stance.
       - reject     : Everything under permissive, plus On-NoSignature
                      reject — every incoming mail must carry a valid
                      DKIM signature. Intended for ingresses where every
                      peer is known to sign.
  7. execvp("/usr/sbin/opendkim", "-f", "-x", "/run/opendkim/opendkim.conf").

*/

#include <cerrno>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <sys/wait.h>
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr const char *OPENSSL         = "/usr/bin/openssl";
constexpr const char *OPENDKIM        = "/usr/sbin/opendkim";
constexpr const char *CONF_BASE       = "/etc/opendkim.conf.base";
constexpr const char *CONF_RUNTIME    = "/run/opendkim/opendkim.conf";
constexpr const char *KEYS_ROOT       = "/etc/opendkim/keys";
constexpr const char *KEY_TABLE       = "/etc/opendkim/KeyTable";
constexpr const char *SIGNING_TABLE   = "/etc/opendkim/SigningTable";
constexpr const char *TRUSTED_HOSTS   = "/etc/opendkim/TrustedHosts";
constexpr const char *IGNORE_HOSTS    = "/etc/opendkim/IgnoreHosts";
constexpr const char *PID_FILE        = "/run/opendkim/opendkim.pid";

std::string
env_or(const char *name, const std::string &fallback = {}) {
  const char *v = std::getenv(name);
  return (v && *v) ? std::string(v) : fallback;
}

std::vector<std::string>
split_ws(const std::string &s) {
  std::vector<std::string> out;
  std::istringstream is(s);
  std::string tok;
  while (is >> tok) out.push_back(tok);
  return out;
}

void
run(const std::vector<const char *> &argv) {
  pid_t pid = fork();
  if (pid < 0) throw std::runtime_error(std::string("fork: ") + std::strerror(errno));
  if (pid == 0) {
    std::vector<char *> a;
    a.reserve(argv.size() + 1);
    for (auto *s : argv) a.push_back(const_cast<char *>(s));
    a.push_back(nullptr);
    execvp(a[0], a.data());
    std::perror(a[0]);
    _exit(127);
  }
  int status = 0;
  if (waitpid(pid, &status, 0) < 0)
    throw std::runtime_error(std::string("waitpid: ") + std::strerror(errno));
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
    std::ostringstream m;
    m << argv[0] << " exited with status " << status;
    throw std::runtime_error(m.str());
  }
}

std::string
read_file(const fs::path &p) {
  std::ifstream in(p, std::ios::binary);
  if (!in) throw std::runtime_error("cannot read " + p.string());
  std::ostringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

void
write_file(const fs::path &p, const std::string &content) {
  std::ofstream out(p, std::ios::binary | std::ios::trunc);
  if (!out) throw std::runtime_error("cannot write " + p.string());
  out << content;
}

void
append_file(const fs::path &p, const std::string &line) {
  std::ofstream out(p, std::ios::app);
  if (!out) throw std::runtime_error("cannot append to " + p.string());
  out << line;
}

// Strip "-----BEGIN/END PUBLIC KEY-----" and every whitespace character from
// a PEM public key, leaving just the base64 body that goes into `p=` of the
// DKIM DNS record.
std::string
pem_body(const std::string &pem) {
  std::string out;
  out.reserve(pem.size());
  bool in_body = false;
  std::istringstream is(pem);
  std::string line;
  while (std::getline(is, line)) {
    if (line.find("-----BEGIN") != std::string::npos) { in_body = true;  continue; }
    if (line.find("-----END")   != std::string::npos) { in_body = false; continue; }
    if (!in_body) continue;
    for (char c : line) if (c != '\r' && c != '\n' && c != ' ' && c != '\t') out += c;
  }
  return out;
}

// BIND-style TXT record split into 255-char strings (RFC 1035), formatted
// like the file that opendkim-genkey used to produce.
std::string
bind_txt_record(const std::string &selector, const std::string &pubkey) {
  const std::string prefix = "v=DKIM1; h=sha256; k=rsa; p=";
  std::string full = prefix + pubkey;

  std::ostringstream out;
  out << selector << "._domainkey\tIN\tTXT\t( ";
  const std::size_t chunk = 255;
  bool first = true;
  for (std::size_t i = 0; i < full.size(); i += chunk) {
    if (!first) out << "\n\t  ";
    first = false;
    out << "\"" << full.substr(i, chunk) << "\"";
  }
  out << " )\n";
  return out.str();
}

void
generate_key(const std::string &domain, const std::string &selector) {
  const fs::path keydir = fs::path(KEYS_ROOT) / domain;
  const fs::path priv   = keydir / (selector + ".private");
  const fs::path pub    = keydir / (selector + ".pub");
  const fs::path txt    = keydir / (selector + ".txt");

  fs::create_directories(keydir);

  std::cerr << "**** Generating DKIM key: selector=" << selector
            << " domain=" << domain << std::endl;

  run({OPENSSL, "genrsa", "-out", priv.c_str(), "2048"});
  run({OPENSSL, "rsa", "-in", priv.c_str(), "-pubout", "-out", pub.c_str()});

  const std::string body = pem_body(read_file(pub));
  const std::string bind = bind_txt_record(selector, body);
  write_file(txt, bind);

  std::cout << "\n"
            << "==================================================================\n"
            << "  DKIM key generated \xe2\x80\x94 add this DNS TXT record to " << domain << ":\n"
            << "==================================================================\n"
            << bind
            << "==================================================================\n\n";
}

enum class Mode { Off, Log, Permissive, Reject };

Mode
parse_mode(const std::string &s) {
  if (s == "off")        return Mode::Off;
  if (s == "log")        return Mode::Log;
  if (s == "permissive") return Mode::Permissive;
  if (s == "reject")     return Mode::Reject;
  throw std::runtime_error(
      "DKIM_DMARC must be one of: off, log, permissive, reject (got \"" + s + "\")");
}

// Compose /run/opendkim/opendkim.conf from the immutable base config plus
// the mode-derived directives. Written under /run/ because /etc/ is not
// writable by the unprivileged user in the scratch runtime image.
void
write_opendkim_conf(Mode mode, const std::string &keyerror_action,
                    const std::string &authserv_id,
                    const std::string &nameservers) {
  std::string conf = read_file(CONF_BASE);
  if (!conf.empty() && conf.back() != '\n') conf += '\n';

  // AuthservID must match opendmarc's TrustedAuthservIDs so opendmarc
  // consumes opendkim's dkim= verdict when deciding DMARC alignment.
  conf += "\nAuthservID       " + authserv_id + "\n";
  if (!nameservers.empty()) {
    // Comma-separated list of DNS servers used exclusively for DKIM key
    // lookups. Bypasses the libc resolver — see opendkim.conf.base for why.
    conf += "Nameservers      " + nameservers + "\n";
  }

  switch (mode) {
    case Mode::Off:
      // Sign outgoing mail only, do NOT verify incoming. No A-R header is
      // added by opendkim in this mode — an operator can effectively
      // disable the whole DKIM verification stage while still signing
      // their own users' mail.
      conf += "\nMode             s\n";
      break;

    case Mode::Log:
      // Verify every incoming signature and stamp the verdict into an
      // Authentication-Results header — but never reject. This is the
      // "monitor before enforce" stage; look for `dkim=fail` /
      // `dkim=none` / `dkim=permerror` in delivered mail before flipping
      // to permissive or reject.
      conf += "\nMode             sv\n"
              "AlwaysAddARHeader true\n";
      break;

    case Mode::Permissive:
      // "DKIM is optional, but if you publish it it must be correct."
      // A missing signature is accepted; a bad signature or an unknown/
      // missing DKIM key means the sender is either misconfigured or
      // forging and gets a hard bounce (5.7.20) or a soft tempfail if
      // DKIM_KEYERROR_ACTION=tempfail.
      conf += "\nMode             sv\n";
      conf += "On-BadSignature  " + keyerror_action + "\n";
      conf += "On-KeyNotFound   " + keyerror_action + "\n";
      break;

    case Mode::Reject:
      // Full enforce: on top of permissive, every incoming mail must
      // carry a valid DKIM signature. Only right for ingresses where
      // every peer is known to sign.
      conf += "\nMode             sv\n";
      conf += "On-BadSignature  " + keyerror_action + "\n";
      conf += "On-KeyNotFound   " + keyerror_action + "\n";
      conf += "On-NoSignature   reject\n";
      break;
  }
  write_file(CONF_RUNTIME, conf);
}

void
write_hosts_file(const fs::path &path, const std::string &hosts_env) {
  std::string content;
  for (const auto &h : split_ws(hosts_env)) {
    content += h;
    content += '\n';
  }
  write_file(path, content);
}

int
healthcheck() {
  std::ifstream in(PID_FILE);
  if (!in) return 1;
  pid_t pid = 0;
  in >> pid;
  if (pid <= 0) return 1;
  return kill(pid, 0) == 0 ? 0 : 1;
}

} // namespace

int main(int argc, char *argv[]) try {
  if (argc > 1 && std::string(argv[1]) == "--healthcheck") return healthcheck();

  std::string domains_env = env_or("DOMAINS", env_or("DOMAIN"));
  std::vector<std::string> domains = split_ws(domains_env);
  if (domains.empty()) {
    std::cerr << "#### ERROR: set DOMAINS (space-separated) or DOMAIN (single)"
              << std::endl;
    return 1;
  }
  const std::string selector = env_or("SELECTOR", "mail");

  // Reset key/signing tables so a shrinking DOMAINS list stays consistent.
  write_file(KEY_TABLE, "");
  write_file(SIGNING_TABLE, "");

  for (const auto &domain : domains) {
    const fs::path keydir = fs::path(KEYS_ROOT) / domain;
    const fs::path priv   = keydir / (selector + ".private");
    if (!fs::exists(priv)) generate_key(domain, selector);

    append_file(KEY_TABLE,
                selector + "._domainkey." + domain + " " +
                domain + ":" + selector + ":" + priv.string() + "\n");
    append_file(SIGNING_TABLE,
                "*@" + domain + " " + selector + "._domainkey." + domain + "\n");
  }

  // TRUSTED_HOSTS → InternalHosts (sign path): senders here are treated as
  // own users and their outgoing mail is signed via SigningTable.
  const std::string trusted_hosts = env_or(
      "TRUSTED_HOSTS",
      "127.0.0.1 ::1 localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16");
  write_hosts_file(TRUSTED_HOSTS, trusted_hosts);

  // ExternalIgnoreList (verify path) is deliberately kept loopback-only:
  // every non-loopback sender's signature must actually be verified,
  // otherwise a bad-signature or unknown-key mail from an RFC1918 client
  // (test-runner, an internal relay, etc.) would slip through unchecked.
  write_hosts_file(IGNORE_HOSTS, "127.0.0.1 ::1 localhost");

  const Mode mode = parse_mode(env_or("DKIM_DMARC", "reject"));
  const std::string keyerror_action = env_or("DKIM_KEYERROR_ACTION", "reject");
  if (keyerror_action != "reject" && keyerror_action != "tempfail") {
    throw std::runtime_error(
        "DKIM_KEYERROR_ACTION must be reject or tempfail (got \"" +
        keyerror_action + "\")");
  }
  const std::string authserv_id = env_or("AUTHSERV_ID", "mail.local");
  const std::string nameservers = env_or("NAMESERVERS", "");
  write_opendkim_conf(mode, keyerror_action, authserv_id, nameservers);

  // If explicit nameservers are given, also overwrite /etc/resolv.conf so
  // opendkim's libc resolver bypasses Docker's embedded 127.0.0.11 (which
  // rewrites authoritative NXDOMAIN responses into SERVFAIL, breaking
  // On-KeyNotFound). Best-effort — failure is not fatal (the container may
  // have a bind-mounted, read-only resolv.conf in some setups).
  if (!nameservers.empty()) {
    std::string resolv;
    for (const auto &ns : split_ws(nameservers)) {
      resolv += "nameserver " + ns + "\n";
    }
    try { write_file("/etc/resolv.conf", resolv); }
    catch (...) { std::cerr << "**** WARNING: could not rewrite /etc/resolv.conf\n"; }
  }

  const char *mode_str =
      mode == Mode::Off        ? "off (sign only, no verify)" :
      mode == Mode::Log        ? "log (verify, add A-R, never reject)" :
      mode == Mode::Permissive ? "permissive (reject bad/unknown-key, accept unsigned)"
                               : "reject (strict: reject bad/unknown-key/unsigned)";
  std::cerr << "**** Starting OpenDKIM in mode=" << mode_str
            << " on port 10026 for: " << domains_env << std::endl;

  const char *exec_argv[] = {"opendkim", "-f", "-x", CONF_RUNTIME, nullptr};
  execv(OPENDKIM, const_cast<char *const *>(exec_argv));
  std::perror(OPENDKIM);
  return 1;
} catch (const std::exception &e) {
  std::cerr << "EXCEPTION: " << e.what() << std::endl;
  return 1;
} catch (...) {
  std::cerr << "UNKNOWN ERROR" << std::endl;
  return 1;
}
