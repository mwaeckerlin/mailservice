FROM mwaeckerlin/very-base AS init
RUN $PKG_INSTALL g++
COPY init.cpp .
RUN g++ -static -Os -flto=auto -fno-rtti -ffunction-sections -fdata-sections \
        -Wl,--gc-sections -Wl,-s -std=c++20 -o init init.cpp
RUN strip -s -R .comment -R .gnu.version --strip-unneeded init

FROM mwaeckerlin/very-base AS build
RUN $PKG_INSTALL opendkim openssl
RUN mkdir -p /etc/opendkim/keys /run/opendkim /tmp \
    && chmod 1777 /tmp \
    && $ALLOW_USER /etc/opendkim /run/opendkim
COPY opendkim.conf /etc/opendkim.conf
COPY --from=init init /usr/bin/init

# Collect only the binaries, shared libraries and configs that the runtime
# actually needs into /root/. The final scratch stage copies /root/ verbatim,
# so nothing not listed here (no shell, no package manager, no perl) ends up
# in the shipped image.
RUN tar cph \
        /etc/opendkim /etc/opendkim.conf /run/opendkim /tmp \
        /etc/passwd /etc/group /etc/nsswitch.conf \
        /usr/sbin/opendkim /usr/bin/openssl /usr/bin/init \
        $(for f in /usr/sbin/opendkim /usr/bin/openssl; do \
              ldd $f | sed -n 's,.* => \([^ ]*\) .*,\1,p'; \
          done 2> /dev/null) 2> /dev/null \
    | tar xpC /root/

FROM mwaeckerlin/scratch
ENV CONTAINERNAME="opendkim" \
    DOMAIN="" \
    DOMAINS="" \
    SELECTOR="mail"
EXPOSE 10026
VOLUME /etc/opendkim/keys
ENTRYPOINT ["/usr/bin/init"]
COPY --from=build /root/ /
