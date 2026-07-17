/**

OpenDMARC init: minimal, shell-free entrypoint for the opendmarc container.

Same idea as mwaeckerlin/nginx's envwrap and the sibling opendkim/init.cpp:
parse env, compose the runtime config, execv() the daemon. The runtime
image contains no /bin/sh, no busybox, no package manager.

Behavior:

  1. Read AUTHSERV_ID (default "mail.local"). This must match opendkim's
     AuthservID so opendmarc trusts opendkim's `Authentication-Results:
     … dkim=pass/fail/...` header when deciding DMARC alignment.
  2. Read TRUSTED_HOSTS (default: loopback + RFC1918). Written to
     /etc/opendmarc/ignore.hosts — connections from these hosts skip
     DMARC processing entirely (own users / internal services).
  3. Read DKIM_DMARC (default "reject"). One knob shared with opendkim
     with four levels — DMARC's take on each:
       - off        : SPFSelfValidate off, no A-R header, milter passes
                      everything through untouched.
       - log        : verify + stamp A-R with `dmarc=pass|fail (p=... dis=none)`
                      but never reject. Monitor mode.
       - permissive : `RejectFailures true` — reject on hard fail against
                      a sender with `p=reject`. `p=quarantine` is treated
                      as accept (Marc's philosophy: no silent junk).
       - reject     : same as permissive on the DMARC side (once you enforce
                      p=reject, adding more never rejects less).
  4. Compose /run/opendmarc/opendmarc.conf from /etc/opendmarc.conf.base
     plus the runtime AuthservID / TrustedAuthservIDs / mode lines.
  5. execv("/usr/sbin/opendmarc", "-f", "-c", "/run/opendmarc/opendmarc.conf").

Supports a --healthcheck mode: reads the pidfile and checks the process is
still alive; matches the compose healthcheck for a shell-less image.

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
#include <unistd.h>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr const char *OPENDMARC       = "/usr/sbin/opendmarc";
constexpr const char *CONF_BASE       = "/etc/opendmarc.conf.base";
constexpr const char *CONF_RUNTIME    = "/run/opendmarc/opendmarc.conf";
constexpr const char *IGNORE_HOSTS    = "/etc/opendmarc/ignore.hosts";
constexpr const char *PID_FILE        = "/run/opendmarc/opendmarc.pid";

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
write_ignore_hosts(const std::string &hosts_env) {
  std::string content;
  for (const auto &h : split_ws(hosts_env)) {
    content += h;
    content += '\n';
  }
  write_file(IGNORE_HOSTS, content);
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

void
write_opendmarc_conf(Mode mode, const std::string &authserv_id) {
  std::string conf = read_file(CONF_BASE);
  if (!conf.empty() && conf.back() != '\n') conf += '\n';
  conf += "\n"
          "AuthservID             " + authserv_id + "\n"
          "TrustedAuthservIDs     " + authserv_id + "\n";

  switch (mode) {
    case Mode::Off:
      // No enforcement, no software header. opendmarc still runs SPF
      // internally (base config), but the result is not acted upon and
      // no `Authentication-Results: … dmarc=…` header is written into
      // the mail. Effectively a pass-through milter.
      conf += "\nRejectFailures         false\n"
              "SoftwareHeader         false\n";
      break;

    case Mode::Log:
      // Verify DMARC and stamp `Authentication-Results: ... dmarc=...
      // (p=... dis=none)` — but never reject. Watch for `dmarc=fail`
      // headers on delivered mail before switching to permissive.
      conf += "\nRejectFailures         false\n"
              "SoftwareHeader         true\n";
      break;

    case Mode::Permissive:
    case Mode::Reject:
      // Reject on hard DMARC fail against a `p=reject` sender. On the
      // DMARC side permissive and reject are the same — once you enforce
      // p=reject, there's nothing stricter left to enable here (the
      // DKIM-side reject-unsigned is opendkim's Mode::Reject alone).
      conf += "\nRejectFailures         true\n"
              "SoftwareHeader         true\n";
      break;
  }
  write_file(CONF_RUNTIME, conf);
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

  const Mode mode = parse_mode(env_or("DKIM_DMARC", "reject"));
  const std::string authserv_id = env_or("AUTHSERV_ID", "mail.local");
  const std::string trusted_hosts = env_or(
      "TRUSTED_HOSTS",
      "127.0.0.1 ::1 localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16");
  const std::string nameservers = env_or("NAMESERVERS", "");

  write_ignore_hosts(trusted_hosts);
  write_opendmarc_conf(mode, authserv_id);

  // Same rationale as opendkim/init.cpp: overwrite /etc/resolv.conf to
  // bypass Docker's embedded resolver which rewrites NXDOMAIN → SERVFAIL.
  if (!nameservers.empty()) {
    std::string resolv;
    for (const auto &ns : split_ws(nameservers)) {
      resolv += "nameserver " + ns + "\n";
    }
    try { write_file("/etc/resolv.conf", resolv); }
    catch (...) { std::cerr << "**** WARNING: could not rewrite /etc/resolv.conf\n"; }
  }

  const char *mode_str =
      mode == Mode::Off        ? "off (pass-through)" :
      mode == Mode::Log        ? "log (verify, stamp A-R, never reject)" :
                                 "reject (reject on p=reject hard fail)";
  std::cerr << "**** Starting OpenDMARC in mode=" << mode_str
            << " on port 8893 (authserv-id " << authserv_id << ")" << std::endl;

  const char *exec_argv[] = {"opendmarc", "-f", "-c", CONF_RUNTIME, nullptr};
  execv(OPENDMARC, const_cast<char *const *>(exec_argv));
  std::perror(OPENDMARC);
  return 1;
} catch (const std::exception &e) {
  std::cerr << "EXCEPTION: " << e.what() << std::endl;
  return 1;
} catch (...) {
  std::cerr << "UNKNOWN ERROR" << std::endl;
  return 1;
}
