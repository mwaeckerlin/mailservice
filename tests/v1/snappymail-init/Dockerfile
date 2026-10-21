# The same base the webmail image is built on, so the unprivileged user
# it runs as exists here too: the data directory this container seeds
# has to belong to that user, or the webmail cannot create its cache and
# answers every request with an empty page.
FROM mwaeckerlin/very-base
COPY seed.sh /usr/local/bin/seed.sh
RUN chmod +x /usr/local/bin/seed.sh
USER root
ENTRYPOINT ["/usr/local/bin/seed.sh"]
