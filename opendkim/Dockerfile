FROM mwaeckerlin/very-base

ENV CONTAINERNAME "opendkim"
ENV DOMAIN        ""
ENV SELECTOR      "mail"

RUN $PKG_INSTALL opendkim opendkim-utils \
    && mkdir -p /etc/opendkim/keys /run/opendkim \
    && chown -R opendkim:opendkim /etc/opendkim /run/opendkim

COPY opendkim.conf /etc/opendkim.conf
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10026
VOLUME /etc/opendkim/keys

USER opendkim
ENTRYPOINT ["/start.sh"]
