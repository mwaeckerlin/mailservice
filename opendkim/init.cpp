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
  6. execvp("/usr/sbin/opendkim", "-f", "-x", "/etc/opendkim.conf").

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
constexpr const char *OPENDKIM_CONF   = "/etc/opendkim.conf";
constexpr const char *KEYS_ROOT       = "/etc/opendkim/keys";
constexpr const char *KEY_TABLE       = "/etc/opendkim/KeyTable";
constexpr const char *SIGNING_TABLE   = "/etc/opendkim/SigningTable";
constexpr const char *TRUSTED_HOSTS   = "/etc/opendkim/TrustedHosts";
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

void
write_trusted_hosts() {
  write_file(TRUSTED_HOSTS,
             "127.0.0.1\n"
             "::1\n"
             "localhost\n"
             "10.0.0.0/8\n"
             "172.16.0.0/12\n"
             "192.168.0.0/16\n");
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

  write_trusted_hosts();

  std::cerr << "**** Starting OpenDKIM (sign+verify) on port 10026 for: "
            << domains_env << std::endl;

  const char *exec_argv[] = {"opendkim", "-f", "-x", OPENDKIM_CONF, nullptr};
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
