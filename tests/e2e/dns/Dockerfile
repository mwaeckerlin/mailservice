FROM alpine:3
RUN apk add --no-cache dnsmasq
COPY dnsmasq.conf /etc/dnsmasq.conf
CMD ["dnsmasq", "--keep-in-foreground", "--log-queries"]
