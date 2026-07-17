FROM mwaeckerlin/very-base AS init
RUN $PKG_INSTALL g++
COPY init.cpp .
RUN g++ -static -Os -flto=auto -fno-rtti -ffunction-sections -fdata-sections \
        -Wl,--gc-sections -Wl,-s -std=c++20 -o init init.cpp
RUN strip -s -R .comment -R .gnu.version --strip-unneeded init

FROM mwaeckerlin/very-base AS build
RUN $PKG_INSTALL opendmarc
RUN mkdir -p /etc/opendmarc /run/opendmarc /tmp \
    && chmod 1777 /tmp \
    && $ALLOW_USER /etc/opendmarc /run/opendmarc
COPY opendmarc.conf /etc/opendmarc.conf.base
COPY --from=init init /usr/bin/init

# Collect only the binaries, shared libraries and configs that the runtime
# actually needs into /root/. The final scratch stage copies /root/ verbatim,
# so nothing not listed here (no shell, no package manager) ends up in the
# shipped image.
RUN tar cph \
        /etc/opendmarc /etc/opendmarc.conf.base /run/opendmarc /tmp \
        /etc/passwd /etc/group /etc/nsswitch.conf \
        /usr/sbin/opendmarc /usr/bin/init \
        $(for f in /usr/sbin/opendmarc; do \
              ldd $f | sed -n 's,.* => \([^ ]*\) .*,\1,p'; \
          done 2> /dev/null) 2> /dev/null \
    | tar xpC /root/

FROM mwaeckerlin/scratch
ENV CONTAINERNAME="opendmarc" \
    DKIM_DMARC="reject" \
    AUTHSERV_ID="mail.local" \
    TRUSTED_HOSTS="127.0.0.1 ::1 localhost 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16" \
    NAMESERVERS=""
EXPOSE 8893
ENTRYPOINT ["/usr/bin/init"]
COPY --from=build /root/ /
